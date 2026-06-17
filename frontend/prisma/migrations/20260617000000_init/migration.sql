CREATE TABLE "Deck" (
  "id" TEXT NOT NULL,
  "ownerId" TEXT NOT NULL,
  "cards" JSONB NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,

  CONSTRAINT "Deck_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "Deck_ownerId_key" ON "Deck"("ownerId");
