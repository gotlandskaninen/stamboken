/* THIS IS A REQUIRED FILE BY PAYLOAD CMS */
import { NotFoundPage, generatePageMetadata } from "@payloadcms/next/views";
import { importMap } from "../importMap";
import config from "@payload-config";

type Args = {
  params: Promise<{ segments: string[] }>;
  searchParams: Promise<Record<string, string>>;
};

export const generateMetadata = ({ params, searchParams }: Args) =>
  generatePageMetadata({ config, params, searchParams });

const NotFound = ({ params, searchParams }: Args) =>
  NotFoundPage({ config, params, searchParams, importMap });

export default NotFound;
