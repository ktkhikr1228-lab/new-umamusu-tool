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
}: {
  title: string;
  tone: "super" | "recommended";
  skills: string[];
  deckSkills: Set<string>;
}) {
  const badgeClass =
    tone === "super"
      ? "bg-rose-50 text-rose-700 border-rose-200"
      : "bg-amber-50 text-amber-700 border-amber-200";

  return (
    <div>
      <span
        className={`mb-2 block w-fit rounded-md border px-2 py-0.5 text-xs font-semibold ${badgeClass}`}
      >
        {title}
      </span>
      <div className="flex flex-wrap gap-2">
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
    <div className="custom-scrollbar grid max-h-[136px] grid-cols-2 gap-4 overflow-y-auto pr-2">
      <SkillGroup
        title="超おすすめスキル"
        tone="super"
        skills={strategyDetail.super_recommended}
        deckSkills={deckSkills}
      />
      <SkillGroup
        title="おすすめスキル"
        tone="recommended"
        skills={strategyDetail.recommended}
        deckSkills={deckSkills}
      />
    </div>
  );
}
