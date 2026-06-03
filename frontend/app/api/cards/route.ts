import { NextResponse } from "next/server";
import cardsData from "../../../src/data/cards.json";

export const dynamic = "force-static";

export function GET() {
  return NextResponse.json({ cards: cardsData });
}
