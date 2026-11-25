export interface Page<T> {
  items: T[];
  total: number;
}

export function paginate<T>(items: T[], page: number, size: number): Page<T> {
  const start = (page - 1) * size;
  return { items: items.slice(start, start + size), total: items.length };
}

export function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export async function fetchAll(urls: string[]): Promise<unknown[]> {
  const responses = await Promise.all(urls.map((u) => fetch(u)));
  return Promise.all(responses.map((r) => r.json()));
}

export function isBlank(value: string | null | undefined): boolean {
  return value === null || value === undefined || value.trim() === "";
}
