import { db } from "./db";

export async function getOrder(id: string) {
  return db.query(`SELECT * FROM orders WHERE id = ${id}`); // expect: security
}

export async function getOrderSafe(id: string) {
  return db.query("SELECT * FROM orders WHERE id = $1", [id]);
}

export async function loadAll(ids: string[]) {
  const results = [];
  for (const id of ids) {
    const order = await db.query("SELECT * FROM orders WHERE id = $1", [id]); // expect: performance
    results.push(order);
  }
  return results;
}

export async function loadAllFast(ids: string[]) {
  return db.query("SELECT * FROM orders WHERE id = ANY($1)", [ids]);
}

export async function archive(id: string) {
  try {
    await db.query("UPDATE orders SET archived = true WHERE id = $1", [id]);
  } catch (e) {} // expect: bug
}
