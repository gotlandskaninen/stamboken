import * as migration_20260615_121804_baseline from "./20260615_121804_baseline";
import * as migration_20261026_074307_media_caption from "./20261026_074307_media_caption";
import * as migration_20261107_055546_users_api_key from "./20261107_055546_users_api_key";

export const migrations = [
  {
    up: migration_20260615_121804_baseline.up,
    down: migration_20260615_121804_baseline.down,
    name: "20260615_121804_baseline",
  },
  {
    up: migration_20261026_074307_media_caption.up,
    down: migration_20261026_074307_media_caption.down,
    name: "20261026_074307_media_caption",
  },
  {
    up: migration_20261107_055546_users_api_key.up,
    down: migration_20261107_055546_users_api_key.down,
    name: "20261107_055546_users_api_key",
  },
];
