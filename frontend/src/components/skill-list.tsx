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
    tone === "super" ? "section-banner-super" : "section-banner-recommended";
  const achievedCount = skills.filter((skill) => deckSkills.has(skill)).length;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex flex-shrink-0 items-center gap-2">
        <span className={`w-fit text-xs ${badgeClass}`}>
          {title}
        </span>
        {skills.length > 0 ? (
          <span className="text-[11px] font-semibold text-muted-foreground">
            編成内 {achievedCount}/{skills.length}
          </span>
        ) : null}
      </div>
      <div
        className={`flex min-h-0 flex-1 flex-wrap content-start gap-2 pr-1 ${
          scrollable
            ? "custom-scrollbar overflow-y-auto"
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
                    ? "skill-chip skill-chip-achieved px-2.5 py-1 text-[11px] font-bold"
                    : "skill-chip px-2.5 py-1 text-[11px] font-bold"
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
    <div className="grid min-h-[168px] grid-cols-1 gap-4 md:h-[216px] md:min-h-0 md:grid-cols-[minmax(360px,0.95fr)_minmax(0,1.45fr)]">
      <div className="soft-panel h-full min-h-0 overflow-hidden rounded-[18px] p-2">
        <SkillGroup
          title="超おすすめスキル"
          tone="super"
          skills={strategyDetail.super_recommended}
          deckSkills={deckSkills}
        />
      </div>
      <div className="soft-panel h-full min-h-0 overflow-hidden rounded-[18px] p-2">
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
