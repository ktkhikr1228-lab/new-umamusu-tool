"use client";

import { StrategyDetail } from "../lib/types";

type SkillListProps = {
  strategyDetail: StrategyDetail;
  deckSkills: Set<string>;
  onSkillClick?: (skill: string) => void;
};

function SkillGroup({
  title,
  tone,
  skills,
  deckSkills,
  scrollable = false,
  onSkillClick,
}: {
  title: string;
  tone: "super" | "recommended";
  skills: string[];
  deckSkills: Set<string>;
  scrollable?: boolean;
  onSkillClick?: (skill: string) => void;
}) {
  const badgeClass =
    tone === "super"
      ? "bg-rose-50 text-rose-700 border-rose-200"
      : "bg-amber-50 text-amber-700 border-amber-200";
  const achievedCount = skills.filter((skill) => deckSkills.has(skill)).length;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex flex-shrink-0 items-center gap-2">
        <span
          className={`block w-fit rounded-md border px-2 py-0.5 text-xs font-semibold ${badgeClass}`}
        >
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
            const baseClass = achieved
              ? "rounded-md border border-emerald-700 bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm"
              : "rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-semibold text-muted-foreground";

            if (!onSkillClick) {
              return (
                <span key={skill} className={baseClass}>
                  {skill}
                  {achieved ? " ✓" : ""}
                </span>
              );
            }

            return (
              <button
                key={skill}
                type="button"
                onClick={() => onSkillClick(skill)}
                title={`「${skill}」を持つサポカを検索`}
                className={`${baseClass} cursor-pointer transition hover:ring-2 hover:ring-ring focus:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
              >
                {skill}
                {achieved ? " ✓" : ""}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

export function SkillList({ strategyDetail, deckSkills, onSkillClick }: SkillListProps) {
  return (
    <div className="grid min-h-[168px] grid-cols-1 gap-4 md:h-[216px] md:min-h-0 md:grid-cols-[minmax(360px,0.95fr)_minmax(0,1.45fr)]">
      <div className="h-full min-h-0 overflow-hidden rounded-md bg-background/40 p-2">
        <SkillGroup
          title="超おすすめスキル"
          tone="super"
          skills={strategyDetail.super_recommended}
          deckSkills={deckSkills}
          scrollable
          onSkillClick={onSkillClick}
        />
      </div>
      <div className="h-full min-h-0 overflow-hidden rounded-md bg-background/40 p-2">
        <SkillGroup
          title="おすすめスキル"
          tone="recommended"
          skills={strategyDetail.recommended}
          deckSkills={deckSkills}
          scrollable
          onSkillClick={onSkillClick}
        />
      </div>
    </div>
  );
}
