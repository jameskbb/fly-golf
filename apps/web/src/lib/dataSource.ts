import { liveSource } from "./api";
import { showcaseSource } from "./showcaseSource";
import { IS_SHOWCASE, type FlyGolfSource } from "./source";

/** The data source this build reads the course and recorded runs from (see ./source.ts). */
export const dataSource: FlyGolfSource = IS_SHOWCASE ? showcaseSource : liveSource;
