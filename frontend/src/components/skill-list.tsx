"use client";

import { StrategyDetail } from "../lib/types";

type SkillListProps = {
  strategyDetail: StrategyDetail;
  deckSkills: Set<string>;
};

function SkillGroup({
  title,
  tone,
  skills,
  deckSkills,
  scrollable = false,
}: {
  title: string;
  tone: "super" | "recommended";
  skills: string[];
  deckSkills: Set<string>;
  scrollable?: boolean;
}) {
  const badgeClass =
    tone === "super"
      ? "bg-rose-50 text-rose-700 border-rose-200"
      : "bg-amber-50 text-amber-700 border-amber-200";

  return (
    <div className="flex min-h-0 flex-col">
      <span
        className={`mb-2 block w-fit flex-shrink-0 rounded-md border px-2 py-0.5 text-xs font-semibold ${badgeClass}`}
      >
        {title}
      </span>
      <div
        className={`flex flex-wrap gap-2 pr-1 ${
          scrollable
            ? "custom-scrollbar min-h-0 overflow-y-auto"
            : "overflow-hidden"
        }`}
      >
        {skills.length === 0 ? (
          <span className="text-xs text-muted-foreground">データなし</span>
        ) : (
          skills.map((skill) => {
            const achieved = deckSkills.has(skill);
            return (
              <span
                key={skill}
                className={
                  achieved
                    ? "rounded-md border border-emerald-700 bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm"
                    : "rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-semibold text-muted-foreground"
                }
              >
                {skill}
                {achieved ? " ✓" : ""}
              </span>
            );
          })
        )}
      </div>
    </div>
  );
}

export function SkillList({ strategyDetail, deckSkills }: SkillListProps) {
  return (
    <div className="grid min-h-[168px] grid-cols-1 gap-4 md:h-[168px] md:min-h-0 md:grid-cols-[minmax(220px,0.75fr)_minmax(0,1.65fr)]">
      <div className="rounded-md bg-background/40 p-2">
        <SkillGroup
          title="超おすすめスキル"
          tone="super"
          skills={strategyDetail.super_recommended}
          deckSkills={deckSkills}
        />
      </div>
      <div className="min-h-0 rounded-md bg-background/40 p-2">
        <SkillGroup
          title="おすすめスキル"
          tone="recommended"
          skills={strategyDetail.recommended}
          deckSkills={deckSkills}
          scrollable
        />
      </div>
    </div>
  );
}
