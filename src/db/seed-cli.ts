// CLI entry point — loads env then runs the seed once and exits.
import "dotenv/config";
import { runSeed } from "./seed";

runSeed()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
