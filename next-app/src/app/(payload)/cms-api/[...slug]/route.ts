/* THIS IS A REQUIRED FILE BY PAYLOAD CMS */
export const dynamic = "force-dynamic";

import {
  REST_DELETE,
  REST_GET,
  REST_PATCH,
  REST_POST,
  REST_PUT,
} from "@payloadcms/next/routes";
import config from "@payload-config";

export const GET = REST_GET(config);
export const POST = REST_POST(config);
export const PATCH = REST_PATCH(config);
export const DELETE = REST_DELETE(config);
export const PUT = REST_PUT(config);
