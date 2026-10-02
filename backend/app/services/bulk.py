"""Bulk intake: tray photos -> counted, identified, described inventory.

Flow:  create batch (preset + answers) -> add tray photos (pieces found, numbered,
grouped) -> describe in background (one AI call per group) -> review -> save.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Optional

from PIL import Image
from sqlmodel import Session, select

from ..config import Settings
from ..models import Batch, BatchGroup, BatchPhoto, Detection, Item
from . import ledger
from .ai import AI
from .images import load_image, resolve_image, save_image
from .matcher import rank
from .presets import PRESETS, normalize_category, resolve_answers
from .segment import crop, find_pieces
from .vision import VisionUnavailable

log = logging.getLogger(__name__)

GROUP_THRESHOLDS = {"lite-v1": 0.95, "openclip-vit-b-32": 0.92}

_running: set[int] = set()
_lock = threading.Lock()


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def preset_of(batch: Batch):
    return PRESETS[batch.preset]


def answers_of(batch: Batch) -> dict:
    return json.loads(batch.answers or "{}")


# ------------------------------------------------------------------ photos


def add_photo(session: Session, ai: AI, settings: Settings, batch: Batch, img: Image.Image) -> str:
    """Find pieces on a tray photo, save crops, assign groups. Returns a warning (or "")."""
    seg = find_pieces(img)

    photo_name = save_image(img, settings.images_dir, 1600)
    saved = Image.open(settings.images_dir / photo_name)
    sx, sy = saved.width / img.width, saved.height / img.height
    photo = BatchPhoto(batch_id=batch.id, image_path=photo_name, width=saved.width, height=saved.height)
    session.add(photo)
    session.flush()

    numbered = session.exec(select(Detection.id).where(Detection.batch_id == batch.id)).all()
    next_no = len(numbered) + 1
    fields, _ = resolve_answers(preset_of(batch), answers_of(batch))
    identical = preset_of(batch).mode == "identical"
    threshold = GROUP_THRESHOLDS.get(getattr(ai.embedder, "name", ""), 0.93)

    # representative embeddings of this batch's groups (identical mode only)
    reps: list[tuple[int, str]] = []
    if identical:
        for g, emb in session.exec(
            select(BatchGroup.id, Detection.embedding)
            .join(Detection, Detection.id == BatchGroup.rep_detection_id)
            .where(BatchGroup.batch_id == batch.id, BatchGroup.include == True)  # noqa: E712
        ).all():
            if emb:
                reps.append((g, emb))

    for i, p in enumerate(seg.pieces):
        piece_img = crop(img, p)
        det = Detection(
            batch_id=batch.id,
            photo_id=photo.id,
            number=next_no + i,
            bbox=json.dumps([round(p.x * sx), round(p.y * sy), round(p.w * sx), round(p.h * sy)]),
            crop_path=save_image(piece_img, settings.images_dir, 800),
        )
        if ai.embedder is not None:
            det.embedding = json.dumps(ai.embedder.embed(piece_img))
        session.add(det)
        session.flush()

        group_id = None
        if identical and det.embedding and reps:
            best = rank(json.loads(det.embedding), reps, top_k=1)
            if best and best[0].score >= threshold:
                group_id = best[0].item_id
        if group_id is None:
            g = BatchGroup(batch_id=batch.id, rep_detection_id=det.id, **fields)
            session.add(g)
            session.flush()
            group_id = g.id
            if identical and det.embedding:
                reps.append((g.id, det.embedding))
        det.group_id = group_id

    session.commit()
    return seg.warning


def set_detection_included(session: Session, det: Detection, include: bool) -> None:
    """Tap a box to drop a false detection (or bring it back)."""
    det.include = include
    session.add(det)
    session.flush()
    group = session.get(BatchGroup, det.group_id)
    members = session.exec(
        select(Detection).where(Detection.group_id == det.group_id, Detection.include == True)  # noqa: E712
    ).all()
    if group:
        if not members:
            group.include = False
        else:
            group.include = True
            if group.rep_detection_id not in {m.id for m in members}:
                group.rep_detection_id = members[0].id
        session.add(group)
    session.commit()


# ---------------------------------------------------------------- describe


def start_describe(engine, ai: AI, settings: Settings, batch_id: int) -> bool:
    with _lock:
        if batch_id in _running:
            return False
        _running.add(batch_id)
    return True


def describe_batch(engine, ai: AI, settings: Settings, batch_id: int) -> None:
    """Runs in the background. One AI call per group, committed one at a time
    so the UI can show progress."""
    try:
        with Session(engine) as session:
            batch = session.get(Batch, batch_id)
            preset = preset_of(batch)
            answers = answers_of(batch)
            fields, attrs = resolve_answers(preset, answers)
            context = "; ".join(f"{k}: {v}" for k, v in {**fields_for_prompt(fields), **attrs}.items())
            hint = preset.ai_hint + (f" The seller says: {context}." if context else "")
            if preset.categories and "category" not in fields:
                hint += " The category MUST be one of: " + ", ".join(preset.categories) + "."

            pending = session.exec(
                select(BatchGroup).where(
                    BatchGroup.batch_id == batch_id,
                    BatchGroup.include == True,  # noqa: E712
                    BatchGroup.status != "done",
                )
            ).all()
            for group in pending:
                det = session.get(Detection, group.rep_detection_id)
                try:
                    img = load_image(resolve_image(settings.images_dir, det.crop_path).read_bytes())
                    draft = ai.vision.describe([img], hint=hint)
                except (VisionUnavailable, FileNotFoundError) as exc:
                    log.warning("describe failed for group %s: %s", group.id, exc)
                    group.status = "failed"
                    session.add(group)
                    session.commit()
                    continue
                group.name = group.name or draft.name
                group.description = group.description or draft.description
                group.tags = group.tags or ", ".join(draft.tags)
                group.color = group.color or draft.color
                if "category" not in fields:
                    group.category = group.category or normalize_category(draft.category, preset.categories)
                if "material" not in fields:
                    group.material = group.material or draft.material
                if "size" not in fields:
                    group.size = group.size or draft.size
                if "price_cents" not in fields and draft.price_cents and not group.price_cents:
                    group.price_cents = draft.price_cents
                group.status = "done"
                session.add(group)
                session.commit()

            if preset.mode == "identical":
                _merge_same_label(session, batch_id)
                _match_existing(session, batch_id)
            batch.status = "review"
            session.add(batch)
            session.commit()
    finally:
        with _lock:
            _running.discard(batch_id)


def fields_for_prompt(fields: dict) -> dict:
    return {k: v for k, v in fields.items() if not k.endswith("_cents")}


def is_running(batch_id: int) -> bool:
    return batch_id in _running


def _merge_same_label(session: Session, batch_id: int) -> None:
    """Identical goods the camera saw as different (lighting, angle) but whose
    label the AI read the same are merged into one group."""
    groups = session.exec(
        select(BatchGroup).where(BatchGroup.batch_id == batch_id, BatchGroup.include == True)  # noqa: E712
        .order_by(BatchGroup.id)
    ).all()
    keep: dict[tuple[str, str], BatchGroup] = {}
    for g in groups:
        if not g.name:
            continue
        key = (norm(g.name), norm(g.size))
        if key in keep:
            for det in session.exec(select(Detection).where(Detection.group_id == g.id)).all():
                det.group_id = keep[key].id
                session.add(det)
            session.delete(g)
        else:
            keep[key] = g
    session.commit()


def _match_existing(session: Session, batch_id: int) -> None:
    for g in session.exec(select(BatchGroup).where(BatchGroup.batch_id == batch_id)).all():
        if not g.name or g.existing_item_id:
            continue
        for it in session.exec(select(Item)).all():
            if norm(it.name) == norm(g.name) and norm(it.size) == norm(g.size):
                g.existing_item_id = it.id
                session.add(g)
                break
    session.commit()


# -------------------------------------------------------------------- save


def group_count(session: Session, group: BatchGroup) -> int:
    if group.count_override is not None:
        return group.count_override
    return len(
        session.exec(
            select(Detection.id).where(Detection.group_id == group.id, Detection.include == True)  # noqa: E712
        ).all()
    )


def save_batch(session: Session, ai: AI, batch: Batch, auto_sku) -> list[Item]:
    """Create or restock one item per included group, recording intake in the
    stock ledger. Returns items in tray-number order (for label printing)."""
    preset = preset_of(batch)
    _, attrs = resolve_answers(preset, answers_of(batch))
    groups = session.exec(
        select(BatchGroup).where(
            BatchGroup.batch_id == batch.id,
            BatchGroup.include == True,  # noqa: E712
            BatchGroup.item_id == None,  # noqa: E711  (idempotent if saved twice)
        )
    ).all()

    def first_number(g: BatchGroup) -> int:
        nums = session.exec(select(Detection.number).where(Detection.group_id == g.id)).all()
        return min(nums) if nums else 0

    saved: list[Item] = []
    for n, g in enumerate(sorted(groups, key=first_number), start=1):
        qty = group_count(session, g)
        if qty <= 0:
            continue
        item: Optional[Item] = session.get(Item, g.existing_item_id) if g.existing_item_id else None
        if item is None and g.size.strip():
            item = next(
                (i for i in session.exec(select(Item)).all()
                 if norm(i.name) == norm(g.name) and norm(i.size) == norm(g.size)),
                None,
            )
        if item is None:
            det = session.get(Detection, g.rep_detection_id)
            item = Item(
                name=g.name.strip() or f"{preset.label} #{first_number(g)}",
                description=g.description,
                category=g.category or (preset.categories[-1] if preset.categories else preset.label),
                tags=g.tags,
                color=g.color,
                size=g.size,
                material=g.material,
                cost_cents=g.cost_cents,
                price_cents=g.price_cents,
                quantity=0,
                image_path=det.crop_path if det else None,
                attributes=json.dumps(attrs) if attrs else "",
            )
            if det and det.embedding and ai.embedder is not None:
                item.embedding, item.embedding_model = det.embedding, ai.embedder.name
            session.add(item)
            session.flush()
            item.sku = auto_sku(item)
        ledger.move(session, item, qty, "intake", batch_id=batch.id, note=f"bulk batch #{batch.id}")
        g.item_id = item.id
        session.add(g)
        saved.append(item)

    batch.status = "saved"
    session.add(batch)
    session.commit()
    for it in saved:
        session.refresh(it)
    return saved
