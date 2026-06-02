"use client";

import { getCardSkills, getTypeStyle } from "../lib/utils";
import { SupportCard } from "../lib/types";

type DeckSlotProps = {
  card?: SupportCard;
  slotIndex: number;
  allTargetSkills: string[];
  onRemove: () => void;
};

export function DeckSlot({
  card,
  slotIndex,
  allTargetSkills,
  onRemove,
}: DeckSlotProps) {
  if (!card) {
    return (
      <div className="flex h-[148px] flex-col items-center justify-center rounded-lg border border-dashed border-border bg-secondary/60 text-muted-foreground">
        <span className="text-3xl font-light">{slotIndex + 1}</span>
        <span className="text-xs font-medium">空き枠</span>
      </div>
    );
  }

  const style = getTypeStyle(card.type);

  return (
    <div
      className={`flex h-[148px] flex-col rounded-lg border bg-card p-3 shadow-sm ${style.border}`}
    >
      <div className="mb-1 flex items-center gap-1.5">
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${style.bg} ${style.text}`}
        >
          {card.type}
        </span>
        <span className="truncate text-[10px] font-semibold text-muted-foreground">
          {card.rarity}
        </span>
      </div>
      <div className="line-clamp-2 text-sm font-semibold leading-tight text-card-foreground">
        {card.name}
      </div>
      <div className="custom-scrollbar mt-1.5 min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="flex flex-wrap gap-1">
          {getCardSkills(card).map((skill) => {
            const target = allTargetSkills.includes(skill);
            return (
              <span
                key={skill}
                className={
                  target
                    ? "rounded bg-emerald-600 px-1.5 py-0.5 text-[9px] font-semibold text-white"
                    : "rounded bg-secondary px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground"
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
        className="mt-1.5 rounded-md bg-secondary px-2 py-1 text-xs font-semibold text-muted-foreground transition-colors hover:text-destructive"
      >
        外す
      </button>
    </div>
  );
}
