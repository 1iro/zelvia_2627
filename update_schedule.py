#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FC町田ゼルビア 試合日程・結果 自動更新スクリプト
================================================
公式サイト（zelvia.co.jp）の「試合日程・結果」ページを取得し、
J1リーグ / ルヴァンカップ / 天皇杯 の日程を schedule.json に反映する。

さらに、Jリーグ公式サイト（jleague.jp）のクラブページにある「戦績」表から
消化済み試合のスコアを取得し、日付が一致する試合（J1に限らず、天皇杯・
ルヴァンカップ・ACL2など schedule.json に載っている大会すべて）に
played / scoreZelvia / scoreOpp を書き込む。

- ACL2（AFCチャンピオンズリーグ2）の個別マッチデー日程は、公式ページの
  「試合日程一覧」にはまだ載らないことが多いため、このスクリプトでは
  既存の schedule.json 内の ACL2 エントリーをそのまま保持する（上書きしない）。
  AFC/クラブから正式な日程が出たら、schedule.json を手動で編集するか、
  このスクリプトに ACL2 用パーサーを追加してください。

- サイト構造が変わるとパースに失敗することがある。日程パースが失敗した場合は
  既存の schedule.json を壊さないよう、変更を書き込まずに終了する
  （GitHub Actions 側は差分が無ければ何もコミットしない）。
  スコア取得の失敗は致命的ではないため、失敗しても日程データだけは更新する。

使い方:
    python3 scripts/update_schedule.py
"""

import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.request import Request, urlopen

SCHEDULE_URL = "https://www.zelvia.co.jp/match/game/series/2026-27/"
RESULTS_URL = "https://www.jleague.jp/club/machida/"
LOGO_BASE = "https://www.zelvia.co.jp/wp-content/themes/zelvia/assets/img/team_logo/"
ROOT = Path(__file__).resolve().parent.parent
SCHEDULE_JSON = ROOT / "schedule.json"

# 全角数字/全角記号を半角に正規化するためのヘルパ
def z2h(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def fetch_html(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    with urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", errors="replace")


# 曜日文字 -> (sort用の分類, 表示ラベル)
DOW_CLASS = {
    "月": "wk", "火": "wk", "水": "wk", "木": "wk", "金": "wk",
    "土": "sat", "日": "sun",
}

MONTH_TO_SEASON_YEAR = {
    # 2026/27シーズン: 8月開幕、翌年6月終了という想定でシーズンをまたぐ年を判定
    8: 2026, 9: 2026, 10: 2026, 11: 2026, 12: 2026,
    1: 2027, 2: 2027, 3: 2027, 4: 2027, 5: 2027, 6: 2027, 7: 2027,
}


def parse_block(comp_key, comp_label, block_text, round_prefix_pattern):
    """
    1つの大会セクションのテキストから試合情報を抽出する。
    パターン例:
      【第9節】10月10日（土）or 10月11日（日）未定〜 ![京都サンガF.C.](...team_kyoto.png) 京都サンガF.C.
      サンガスタジアム by ＫＹＯＣＥＲＡ/AWAY
    """
    entries = []
    pattern = re.compile(
        r"【(?P<round>[^】]+)】\s*"
        r"(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日（(?P<dow1>[月火水木金土日])）"
        r"(?:or\s*(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日（(?P<dow2>[月火水木金土日])）)?"
        r"\s*(?P<time>未定|\d{1,2}:\d{2})[〜~]\s*"
        r"!\[(?P<opp_alt>[^\]]*)\]\((?P<logo_url>[^)]+)\)\s*"
        r"(?P<opp_name>[^\n]+?)\s*\n"
        r"(?P<stadium>[^\n/]*)/(?P<ha>HOME|AWAY)",
        re.MULTILINE,
    )
    for m in pattern.finditer(block_text):
        d = m.groupdict()
        month1, day1 = int(d["m1"]), int(d["d1"])
        year1 = MONTH_TO_SEASON_YEAR.get(month1, 2026)
        sort_date = f"{year1:04d}-{month1:02d}-{day1:02d}"

        if d["m2"]:
            date_disp = f"{month1:02d}.{day1:02d} or {int(d['m2']):02d}.{int(d['d2']):02d}"
            day_label = f"{d['dow1']}/{d['dow2']}"
        else:
            date_disp = f"{month1:02d}.{day1:02d}"
            day_label = d["dow1"]

        day_class = DOW_CLASS.get(d["dow1"], "wk")
        time_disp = d["time"] if d["time"] == "未定" else d["time"]
        stadium = z2h(d["stadium"]).strip() or "未定"
        opp_name = z2h(d["opp_name"]).strip()
        # 消化済み試合はスコアが付く（例: "FC東京 ◯1 - 5"）ので除去する
        opp_name = re.split(r"\s*[○◯●△]\s*\d", opp_name)[0].strip()
        logo_file = d["logo_url"].rsplit("/", 1)[-1]

        round_raw = z2h(d["round"])
        # J1は「第9節」→ 9 のように数値だけ取り出す。それ以外（4回戦, 2回戦など）はそのまま。
        round_num_match = re.match(r"第(\d+)節", round_raw)
        round_val = int(round_num_match.group(1)) if round_num_match else round_raw

        entries.append({
            "comp": comp_key,
            "round": round_val,
            "home": True if d["ha"] == "HOME" else False,
            "sort": sort_date,
            "date": date_disp,
            "day": day_class,
            "dayLabel": day_label,
            "time": time_disp,
            "opp": opp_name,
            "logo": logo_file,
            "stadium": stadium,
        })
    return entries


def split_sections(markdown_like_text: str):
    """
    「試合日程一覧」以降を大会ごとのセクションに分割する。
    見出し例:
      ### 2026/27明治安田J1リーグ
      ### 2026/27Ｊリーグ ヤマザキビスケットルヴァンカップ【1stラウンド】
      ### 天皇杯 JFA 第 106 回全日本サッカー選手権大会
    """
    idx = markdown_like_text.find("試合日程一覧")
    text = markdown_like_text[idx:] if idx != -1 else markdown_like_text

    sections = {}
    parts = re.split(r"\n###\s*", text)
    for part in parts[1:]:
        header, _, body = part.partition("\n")
        header = z2h(header)
        if "J1" in header or "Ｊ１" in header:
            sections["J1"] = body
        elif "ルヴァン" in header:
            sections["YBC"] = body
        elif "天皇杯" in header:
            sections["EMP"] = body
    return sections


def html_to_pseudo_markdown(html: str) -> str:
    """
    非常に簡易的な変換: <img alt="x" src="y"> を ![x](y) に、
    見出し等はそのまま残しつつ改行を整える。
    完全なMarkdown変換ではないが、正規表現パターンが拾えれば十分。
    """
    html = re.sub(
        r'<img[^>]*alt="([^"]*)"[^>]*src="([^"]+)"[^>]*>',
        r"![\1](\2)",
        html,
    )
    html = re.sub(
        r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>',
        r"![\2](\1)",
        html,
    )
    html = re.sub(r"<h3[^>]*>", "\n### ", html)
    html = re.sub(r"</h3>", "\n", html)
    html = re.sub(r"<(li|p|div)[^>]*>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)  # 残りのタグは除去
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{2,}", "\n", html)
    return html


def extract_table_rows(html: str, near_heading: str):
    """
    指定した見出し文字列（例:「戦績」）の後に最初に現れる <table> を探し、
    行ごとにセルのテキストのリストとして返す。
    """
    idx = html.find(near_heading)
    if idx == -1:
        return []
    table_start = html.find("<table", idx)
    if table_start == -1:
        return []
    table_end = html.find("</table>", table_start)
    if table_end == -1:
        return []
    table_html = html[table_start:table_end]

    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)
        clean_cells = []
        for c in cells:
            c = re.sub(r"<[^>]+>", "", c)
            c = z2h(c).strip()
            clean_cells.append(c)
        if clean_cells:
            rows.append(clean_cells)
    return rows


def parse_results(html: str):
    """
    jleague.jp クラブページの「戦績」表から、消化済み試合のスコアを抽出する。
    戻り値: [{"sort": "YYYY-MM-DD", "scoreZelvia": int, "scoreOpp": int}, ...]

    表の想定フォーマット（見出し行を含む）:
      年月日 | KO時刻 | 対戦相手 | 会場 | スコア | 大会 | ...
      26/8/23 | 19:36 | 浦和 | MUFG国立 | 勝 3-1 | 明治安田Ｊ１ | ...

    スコア欄は常に「町田自身の得点-相手の得点」の順で書かれているため、
    home/away を問わずそのまま scoreZelvia / scoreOpp として使える。
    """
    rows = extract_table_rows(html, "戦績")
    results = []
    date_re = re.compile(r"^(\d{2})/(\d{1,2})/(\d{1,2})$")
    score_re = re.compile(r"(\d+)\s*-\s*(\d+)")

    for row in rows:
        if not row or not date_re.match(row[0]):
            continue  # 見出し行や不正な行はスキップ
        yy, mm, dd = date_re.match(row[0]).groups()
        year = 2000 + int(yy)
        sort_date = f"{year:04d}-{int(mm):02d}-{int(dd):02d}"

        score_cell = next((c for c in row if score_re.search(c)), None)
        if not score_cell:
            continue
        m = score_re.search(score_cell)
        results.append({
            "sort": sort_date,
            "scoreZelvia": int(m.group(1)),
            "scoreOpp": int(m.group(2)),
        })
    return results


def main():
    try:
        raw_html = fetch_html(SCHEDULE_URL)
    except Exception as e:
        print(f"[ERROR] ページ取得に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    pseudo_md = html_to_pseudo_markdown(raw_html)
    sections = split_sections(pseudo_md)

    new_entries = []
    if "J1" in sections:
        new_entries += parse_block("J1", "明治安田J1リーグ", sections["J1"], r"第\d+節")
    if "YBC" in sections:
        new_entries += parse_block("YBC", "ルヴァンカップ", sections["YBC"], r".+")
    # 天皇杯は「対戦相手未定」の間はスタジアム/HOME・AWAY表記が省略され
    # フォーマットが崩れやすいため自動パース対象から外し、既存データを保持する。

    if len(new_entries) < 30:
        # J1だけで38試合前後あるはずなので、極端に少ない場合はサイト構造の変化を疑い、
        # 既存ファイルを壊さないよう安全側に倒して終了する。
        print(f"[WARN] 取得できた試合数が少なすぎます（{len(new_entries)}件）。"
              f"サイト構造が変わった可能性があるため、schedule.json は更新しません。", file=sys.stderr)
        sys.exit(2)

    # 既存の schedule.json を読み込み、EMP・ACL2エントリーは保持したまま J1/YBC のみ差し替える
    if SCHEDULE_JSON.exists():
        existing = json.loads(SCHEDULE_JSON.read_text(encoding="utf-8"))
    else:
        existing = []
    kept_entries = [e for e in existing if e.get("comp") in ("EMP", "ACL2")]

    merged = new_entries + kept_entries
    merged.sort(key=lambda e: e["sort"])

    # jleague.jp の「戦績」表から消化済み試合のスコアを取得してマージする。
    # J1に限らず、天皇杯・ルヴァン・ACL2など、この表に載る大会はすべて対象にする
    # （日付が一致すれば反映するだけなので、大会を問わない）。
    # ここが失敗しても日程データ自体は活かしたいので、例外は握りつぶして続行する。
    scored_count = 0
    try:
        results_html = fetch_html(RESULTS_URL)
        results = parse_results(results_html)
        results_by_date = {r["sort"]: r for r in results}
        for m in merged:
            r = results_by_date.get(m["sort"])
            if r:
                m["played"] = True
                m["scoreZelvia"] = r["scoreZelvia"]
                m["scoreOpp"] = r["scoreOpp"]
                scored_count += 1
    except Exception as e:
        print(f"[WARN] 試合結果（スコア）の取得に失敗しました。日程のみ更新します: {e}", file=sys.stderr)

    SCHEDULE_JSON.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] schedule.json を更新しました（{len(merged)}件: "
          f"J1/YBC {len(new_entries)}件 + EMP/ACL2(保持) {len(kept_entries)}件 / "
          f"スコア反映 {scored_count}件）")


if __name__ == "__main__":
    main()
