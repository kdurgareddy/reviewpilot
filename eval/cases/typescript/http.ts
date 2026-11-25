import https from "https";
import { exec } from "child_process";

export const insecureAgent = new https.Agent({ rejectUnauthorized: false }); // expect: security

export function convert(file: string) {
  exec(`convert ${file} out.png`); // expect: security
}

export function parse(input: string) {
  return eval(input); // expect: security
}

export function retryDelay(attempt: number) {
  return Math.min(1000 * 2 ** attempt, 30000);
}
