export default function Placeholder({ name }: { name: string }) {
  return <p data-island={name}>TRACE: {name} (placeholder)</p>;
}
