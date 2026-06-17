import { Prisma } from "@prisma/client";
import { NextRequest, NextResponse } from "next/server";
import { getPrisma } from "../../../src/lib/prisma";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function normalizeOwnerId(value: unknown) {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, 128);
}

function normalizeDeck(value: unknown) {
  if (!Array.isArray(value)) return null;
  return value.slice(0, 6);
}

export async function GET(request: NextRequest) {
  const ownerId = normalizeOwnerId(request.nextUrl.searchParams.get("ownerId"));
  if (!ownerId) {
    return NextResponse.json({ deck: [] });
  }

  const prisma = getPrisma();
  if (!prisma) {
    return NextResponse.json({ deck: [] });
  }

  const savedDeck = await prisma.deck.findUnique({
    where: { ownerId },
    select: { cards: true },
  });

  return NextResponse.json({ deck: savedDeck?.cards ?? [] });
}

export async function POST(request: NextRequest) {
  const body = (await request.json()) as {
    ownerId?: unknown;
    deck?: unknown;
  };
  const ownerId = normalizeOwnerId(body.ownerId);
  const deck = normalizeDeck(body.deck);

  if (!ownerId || !deck) {
    return NextResponse.json(
      { error: "ownerId and deck are required." },
      { status: 400 }
    );
  }

  const prisma = getPrisma();
  if (!prisma) {
    return NextResponse.json(
      { error: "DATABASE_URL is not configured." },
      { status: 503 }
    );
  }

  await prisma.deck.upsert({
    where: { ownerId },
    update: { cards: deck as Prisma.InputJsonValue },
    create: {
      ownerId,
      cards: deck as Prisma.InputJsonValue,
    },
  });

  return NextResponse.json({ status: "success" });
}
