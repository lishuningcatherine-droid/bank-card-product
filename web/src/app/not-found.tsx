import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-xl space-y-3 py-12">
      <h1 className="text-3xl">Page not found</h1>
      <p>The page you&apos;re looking for doesn&apos;t exist, or the product is no longer published.</p>
      <Link href="/" className="font-medium">Go to the home page</Link>
    </div>
  );
}
