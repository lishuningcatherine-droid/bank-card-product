/** Generic product artwork. Bank logos and card art are not used (their terms of use are not confirmed), so every
 * product gets the same neutral shape for its type, drawn with theme tokens only. */
export function PlaceholderArt({ type, className = "" }: { type: string; className?: string }) {
  const card = type === "credit_card";
  return (
    <svg viewBox="0 0 160 100" role="img" aria-label={card ? "Generic card illustration" : "Generic account illustration"} className={`h-auto w-full ${className}`}>
      <rect x="1" y="1" width="158" height="98" rx="10" className="fill-navy-50 stroke-border" strokeWidth="2" />
      {card ? (
        <>
          <rect x="16" y="34" width="26" height="20" rx="4" className="fill-surface stroke-border-strong" strokeWidth="1.5" />
          <rect x="16" y="70" width="80" height="6" rx="3" className="fill-border" />
          <rect x="104" y="70" width="40" height="6" rx="3" className="fill-border" />
        </>
      ) : (
        <>
          <path d="M40 44 L80 24 L120 44 Z" className="fill-surface stroke-border-strong" strokeWidth="1.5" />
          {[52, 72, 92, 108].map((x) => <rect key={x} x={x - 4} y="48" width="8" height="26" rx="2" className="fill-border" />)}
          <rect x="38" y="78" width="84" height="6" rx="3" className="fill-border-strong" />
        </>
      )}
    </svg>
  );
}
