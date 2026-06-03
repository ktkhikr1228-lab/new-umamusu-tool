import { NextResponse } from "next/server";
import raceData from "../../../src/data/race_data.json";

export const dynamic = "force-static";

export function GET() {
  return NextResponse.json(raceData);
}
