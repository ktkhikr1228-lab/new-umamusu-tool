-- RaceSkillテーブルのスキル名修正(2026-07-03 skill_master照合による)
-- 表記ゆれ(半角!)10件 + 誤字3件。
-- 修正先と同名の行が既に存在する場合は誤記行を削除、なければ改名する。
--
-- 実行方法(ラズパイ):
--   sudo -u postgres psql uma_tool -f fix_skill_names.sql

BEGIN;

CREATE TEMP TABLE skill_fixes (wrong text, correct text) ON COMMIT DROP;
INSERT INTO skill_fixes VALUES
  ('いいとこ入った!',     'いいとこ入った！'),
  ('お先に失礼っ!',       'お先に失礼っ！'),
  ('かっとばせ!',         'かっとばせ！'),
  ('ぶっちぎり!',         'ぶっちぎり！'),
  ('勝負はここから!',     '勝負はここから！'),
  ('押し通る!',           '押し通る！'),
  ('活路を拓く!',         '活路を拓く！'),
  ('誰より前へ!',         '誰より前へ！'),
  ('逃げるが勝ち!',       '逃げるが勝ち！'),
  ('遊びはおしまいっ!',   '遊びはおしまいっ！'),
  ('勝負を賭けて',        '勝負を懸けて'),
  ('孤線のプロフェッサー', '弧線のプロフェッサー'),
  ('秘めたる闘魂',        '秘めた闘魂');

-- 1. 修正先が同じ(race, strategy, tier)に既に存在する誤記行は削除
DELETE FROM "RaceSkill" r
USING skill_fixes f
WHERE r.skill = f.wrong
  AND EXISTS (
    SELECT 1 FROM "RaceSkill" t
    WHERE t.race = r.race AND t.strategy = r.strategy
      AND t.tier = r.tier AND t.skill = f.correct
  );

-- 2. 残りは正しい名前に改名(memoに履歴を残す)
UPDATE "RaceSkill" r
SET skill = f.correct,
    memo = trim(BOTH ' ' FROM r.memo || ' auto_fix:' || f.wrong || '->' || f.correct),
    "updatedAt" = now()
FROM skill_fixes f
WHERE r.skill = f.wrong;

-- 結果確認: 誤記が残っていないこと(0行になるはず)
SELECT r.skill, count(*)
FROM "RaceSkill" r
JOIN skill_fixes f ON r.skill = f.wrong
GROUP BY r.skill;

COMMIT;
