import { useRef } from "react";

/**
 * Big "take a photo" button. On phones `capture="environment"` opens the rear
 * camera directly (works over plain http on your Wi-Fi, unlike getUserMedia).
 * On laptops it opens a file picker, and most OSes offer the webcam there too.
 */
export function PhotoButton({
  label,
  onPhoto,
  disabled,
  variant = "primary",
  multiple = false,
}: {
  label: string;
  onPhoto: (file: File) => void;
  disabled?: boolean;
  variant?: "primary" | "secondary";
  /** Allow picking several photos from the gallery (each is passed to onPhoto in turn). */
  multiple?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        type="button"
        className={`btn btn-${variant} btn-big`}
        disabled={disabled}
        onClick={() => input.current?.click()}
      >
        <CameraIcon /> {label}
      </button>
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture={multiple ? undefined : "environment"}
        multiple={multiple}
        hidden
        onChange={(e) => {
          Array.from(e.target.files ?? []).forEach((f) => onPhoto(f));
          e.target.value = "";
        }}
      />
    </>
  );
}

function CameraIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" />
      <circle cx="12" cy="13.5" r="3.5" />
    </svg>
  );
}
