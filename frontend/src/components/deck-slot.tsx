"use client";

import { getCardSkills, getTypeStyle } from "../lib/utils";
import { SupportCard, UsageMode } from "../lib/types";

type DeckSlotProps = {
  card?: SupportCard;
  slotIndex: number;
  allTargetSkills: string[];
  usageMode: UsageMode;
  onRemove: () => void;
};

export function DeckSlot({
  card,
  slotIndex,
  allTargetSkills,
  usageMode,
  onRemove,
}: DeckSlotProps) {
  if (!card) {
    return (
      <div className="soft-panel flex h-[148px] flex-col items-center justify-center rounded-[18px] border-dashed text-muted-foreground">
        <span className="text-3xl font-light">{slotIndex + 1}</span>
        <span className="text-xs font-medium">空き枠</span>
      </div>
    );
  }

  const style = getTypeStyle(card.type);

  return (
    <div
      className={`soft-panel flex h-[148px] flex-col rounded-[18px] p-3 ${style.border}`}
    >
      <div className="mb-1 flex items-center gap-1.5">
        <span
          className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${style.bg} ${style.text}`}
        >
          {card.type}
        </span>
        <span
          className={`rarity-badge truncate text-[10px] ${
            card.rarity === "SSR" ? "rarity-badge-ssr" : ""
          }`}
        >
          {card.rarity}
        </span>
      </div>
      <div className="line-clamp-2 text-sm font-semibold leading-tight text-card-foreground">
        {card.name}
      </div>
      <div className="custom-scrollbar mt-1.5 min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="flex flex-wrap gap-1">
          {getCardSkills(card, usageMode).map((skill) => {
            const target = allTargetSkills.includes(skill);
            return (
              <span
                key={skill}
                className={
                  target
                    ? "skill-chip skill-chip-achieved px-1.5 py-0.5 text-[9px] font-bold"
                    : "skill-chip px-1.5 py-0.5 text-[9px] font-bold"
                }
              >
                {skill}
              </span>
            );
          })}
        </div>
      </div>
      <button
        onClick={onRemove}
        className="material-button-secondary mt-1.5 rounded-md px-2 py-1 text-xs font-semibold transition hover:text-destructive"
      >
        外す
      </button>
    </div>
  );
}
