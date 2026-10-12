import { useEffect, useRef, type ReactNode } from "react";
export function Modal({
  title,
  closeLabel,
  onClose,
  children,
}: {
  title: string;
  closeLabel: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog ref={ref} onCancel={onClose} aria-label={title}>
      <header>
        <h2>{title}</h2>
        <button aria-label={closeLabel} onClick={onClose}>
          ×
        </button>
      </header>
      {children}
    </dialog>
  );
}
