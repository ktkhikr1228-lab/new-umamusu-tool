import { SupportCard } from "./types";

export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function getCardSkills(card: SupportCard) {
  return [...(card.skills || []), ...(card.rare_skills || [])];
}

export function scoreCard(
  card: SupportCard,
  missingSuperSkills: string[],
  missingRecommendedSkills: string[]
) {
  return getCardSkills(card).reduce((score, skill) => {
    if (missingSuperSkills.includes(skill)) return score + 3;
    if (missingRecommendedSkills.includes(skill)) return score + 1;
    return score;
  }, 0);
}

export function getTypeStyle(type: string) {
  if (type.includes("スピード")) {
    return {
      label: "スピード",
      icon: "S",
      bg: "bg-sky-50",
      text: "text-sky-700",
      border: "border-sky-200",
    };
  }
  if (type.includes("スタミナ")) {
    return {
      label: "スタミナ",
      icon: "St",
      bg: "bg-orange-50",
      text: "text-orange-700",
      border: "border-orange-200",
    };
  }
  if (type.includes("パワー")) {
    return {
      label: "パワー",
      icon: "P",
      bg: "bg-rose-50",
      text: "text-rose-700",
      border: "border-rose-200",
    };
  }
  if (type.includes("根性")) {
    return {
      label: "根性",
      icon: "G",
      bg: "bg-red-50",
      text: "text-red-700",
      border: "border-red-200",
    };
  }
  if (type.includes("賢さ")) {
    return {
      label: "賢さ",
      icon: "W",
      bg: "bg-emerald-50",
      text: "text-emerald-700",
      border: "border-emerald-200",
    };
  }
  return {
    label: type,
    icon: "F",
    bg: "bg-slate-100",
    text: "text-slate-700",
    border: "border-slate-200",
  };
}
