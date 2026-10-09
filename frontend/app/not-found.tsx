import Link from 'next/link';

/** Friendly 404 — no default Next.js branding. */
export default function NotFound() {
  return (
    <>
      <div className="bc">
        <b>Not found</b>
      </div>
      <div className="page">
        <h1 style={{ fontSize: 26 }}>That page does not exist</h1>
        <p className="m" style={{ margin: '6px 0 24px', maxWidth: 620 }}>
          The address you followed is not part of this product. Nothing has changed.
        </p>
        <div className="row" style={{ gap: 8 }}>
          <Link className="btn" href="/">
            Back to overview
          </Link>
          <Link className="btn o" href="/workflows">
            See discovered workflows
          </Link>
        </div>
      </div>
    </>
  );
}