export type StrategyDetail = {
  super_recommended: string[];
  recommended: string[];
};

export type RaceData = Record<string, Record<string, StrategyDetail>>;

export type SupportCard = {
  id: number;
  name: string;
  char: string;
  card: string;
  rarity: string;
  type: string;
  skills: string[];
  rare_skills?: string[];
};
