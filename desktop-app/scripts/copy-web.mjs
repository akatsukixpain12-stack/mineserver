import { mkdirSync, copyFileSync } from "node:fs";
import { resolve } from "node:path";
const root=resolve(process.cwd(),"..","..");
const out=resolve(process.cwd(),"web","index.html");
mkdirSync(resolve(process.cwd(),"web"),{recursive:true});
copyFileSync(resolve(root,"index.html"),out);
console.log("Copied Mineserver web UI.");
