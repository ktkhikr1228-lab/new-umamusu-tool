-- CreateTable
CREATE TABLE "RaceSkill" (
    "id" SERIAL NOT NULL,
    "event" TEXT NOT NULL DEFAULT '',
    "race" TEXT NOT NULL,
    "strategy" TEXT NOT NULL,
    "tier" TEXT NOT NULL,
    "skill" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'draft',
    "sourceFile" TEXT NOT NULL DEFAULT '',
    "memo" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "RaceSkill_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "RaceSkill_status_idx" ON "RaceSkill"("status");

-- CreateIndex
CREATE INDEX "RaceSkill_race_strategy_idx" ON "RaceSkill"("race", "strategy");

-- CreateIndex
CREATE UNIQUE INDEX "RaceSkill_race_strategy_tier_skill_key" ON "RaceSkill"("race", "strategy", "tier", "skill");
