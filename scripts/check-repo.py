#!/usr/bin/env python3
"""
リポジトリの点検。2つのことを調べる。

    python3 scripts/check-repo.py            # 点検する
    python3 scripts/check-repo.py --markdown # 報告にそのまま貼れる形で出す

1. フォルダーのズレ
   CLAUDE.md の「フォルダーの役割」の表と、実際にあるフォルダーを突き合わせる。
   Claude が作業中に黙ってフォルダーを増やしても、これを実行すれば分かる。

2. 残骸ファイル
   CLAUDE.md の表で役割に「一時」と書いてあるフォルダー（`work/` など）に、
   いつのものか分からないファイルが溜まっていないかを見る。
   Git に入らないので気づきにくいが、ディスクは食う。
   「.gitignore で除外されている＝一時置き場」とは限らない（個人情報を
   含むので Git に入れないだけの本番フォルダーもある）ため、判定は
   CLAUDE.md の表を見る。

どのリポジトリでもそのまま動く（このファイルをコピーするだけ）。
どこから実行しても、このファイルが置かれたリポジトリを点検する。
"""
import re
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    """点検するリポジトリは、このファイルの置き場所で決める。

    実行した場所（カレントディレクトリ）で決めると、複数のリポジトリを
    並べて開くセッションで誤る。親フォルダーから実行すると CLAUDE.md が
    見つからないと言って止まり、別のリポジトリの中から実行すると
    そちらを黙って点検して「一致」と答える（2026-09-24 に実際に確認した）。
    """
    here = Path(__file__).resolve().parent
    try:
        out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=here,
                             capture_output=True, text=True, check=True).stdout.strip()
        return Path(out)
    except Exception:
        return here.parent


def declared_dirs(claude_md: Path) -> set[str]:
    """CLAUDE.md の中の `パス/` 形式の記述を拾う。<製品> などは * に置き換える。"""
    if not claude_md.exists():
        return set()
    text = claude_md.read_text(encoding='utf-8')
    # ``` で囲まれたコードブロックを先に取り除く。
    # 3連バッククォートが残っていると、以降のバッククォートの対応がずれて、
    # 表に書いたパスを1つも拾えなくなる（CLAUDE.md に構成図を載せている
    # リポジトリで実際に起きた）。
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'~~~[\s\S]*?~~~', '', text)
    found = set()
    for token in re.findall(r'`([^`]+)`', text):
        token = token.strip()
        if not token.endswith('/'):
            continue                      # フォルダーの表記は末尾に / を付ける決まり
        token = token.rstrip('/')
        token = re.sub(r'<[^>]+>', '*', token)   # products/<製品> → products/*
        if token and not token.startswith('/'):
            found.add(token)
    return found


def actual_dirs(root: Path) -> set[str]:
    """Git が管理しているファイルから、実際に使われているフォルダーを起こす。"""
    # -z を使わないと、日本語のファイル名が "\346..." の形で返ってきて名前が壊れる
    raw = subprocess.run(['git', 'ls-files', '-z'], cwd=root,
                         capture_output=True).stdout.decode('utf-8')
    out = [f for f in raw.split('\0') if f]
    dirs = set()
    for f in out:
        p = Path(f).parent
        while str(p) not in ('.', ''):
            dirs.add(str(p))
            p = p.parent
    return dirs


def matches(actual: str, declared: set[str]) -> bool:
    """宣言されたパスのどれかに当てはまるか。

    `products/<製品>/`  → その1階層だけ（`products/dc-assist` は可、その中は不可）
    `archive/**/`       → その下は何階層でも自由（退避置き場・年別フォルダなど）
    """
    for d in declared:
        pat = re.escape(d).replace(r'\*\*', '\x00').replace(r'\*', '[^/]+')
        pat = pat.replace('\x00', '.+')
        if re.match('^' + pat + '$', actual):
            return True
    return False


def is_ancestor_of_declared(actual: str, declared: set[str]) -> bool:
    """`products/<製品>/` を宣言したら、その親の `products/` も宣言済みとみなす。

    逆はしない。親が宣言されているからといって、その中に作られたフォルダーを
    自動で許すと、黙って増えたフォルダーを見逃してしまう。
    中に自由にフォルダーを作ってよい場所は、CLAUDE.md に `archive/<日付>/` の
    ように書いて明示する。
    """
    return any(d.startswith(actual + '/') for d in declared)


def temp_dirs(root: Path) -> list[str]:
    """一時置き場を拾う。

    「.gitignore で除外されている＝一時置き場」ではない。
    個人情報を含むので Git に入れないだけの、本番の作業フォルダーもある
    （人事評価のリポジトリで実際にそうなっていた）。それを残骸として
    報告すると誤報になる。

    そこで、CLAUDE.md のフォルダーの表で **役割に「一時」と書いてある行**
    だけを一時置き場として扱う。判定を人が読める場所に置くため。
    """
    md = root / 'CLAUDE.md'
    if not md.exists():
        return []
    text = re.sub(r'```[\s\S]*?```', '', md.read_text(encoding='utf-8'))
    out = []
    for line in text.splitlines():
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 2:
            continue
        m = re.fullmatch(r'`([^`]+/)`', cells[0])
        if not m or '一時' not in ' '.join(cells[1:]):
            continue
        d = m.group(1).rstrip('/')
        if '*' not in d and '<' not in d and (root / d).is_dir():
            out.append(d)
    return out


def residue(root: Path) -> list[dict]:
    """一時フォルダーの中身を、直下のフォルダーごとに集計する。

    Git に入っているファイルの数も数える（'tracked'）。一時置き場を
    .gitignore で除外し忘れると中身がコミットされていることがあり、
    そのまま「Git には入らないので消しても失われない」と案内すると誤りになる
    （2026-09-24 に模擬リポで確認した）。
    """
    import time
    now = time.time()
    rows = []
    for d in temp_dirs(root):
        base = root / d
        raw = subprocess.run(['git', 'ls-files', '-z', '--', d], cwd=root,
                             capture_output=True).stdout.decode('utf-8')
        tracked = {f for f in raw.split('\0') if f}
        for child in sorted(base.iterdir()):
            if child.name.startswith('.'):
                continue          # .gitkeep など、置いておくためのファイルは残骸ではない
            files = [f for f in child.rglob('*') if f.is_file()] if child.is_dir() else [child]
            if not files:
                continue
            size = sum(f.stat().st_size for f in files)
            mtime = max(f.stat().st_mtime for f in files)
            n_tracked = sum(1 for f in files if f.relative_to(root).as_posix() in tracked)
            # フォルダーだけ末尾に / を付ける（ファイルに付けると別物に見える）
            path = f'{d}/{child.name}' + ('/' if child.is_dir() else '')
            rows.append({'path': path, 'files': len(files), 'tracked': n_tracked,
                         'mb': size / 1024 / 1024, 'days': (now - mtime) / 86400})
    return sorted(rows, key=lambda r: -r['days'])


def main() -> int:
    md = '--markdown' in sys.argv
    root = repo_root()
    declared = declared_dirs(root / 'CLAUDE.md')
    actual = actual_dirs(root)

    if not declared:
        print('CLAUDE.md にフォルダーの記述が見つかりません（`パス/` の形で書いてください）')
        return 2

    # 表にない＝知らないうちに増えたフォルダー
    unknown = sorted(a for a in actual
                     if not a.startswith('.')
                     and not matches(a, declared)
                     and not is_ancestor_of_declared(a, declared))

    # 表にあるのに実在しないフォルダー。
    # ただし次は数えない。CLAUDE.md には説明のために書いただけのパスが混ざるため。
    #   ・別のリポジトリのパス（第一階層がこのリポジトリに無い）
    #   ・書式の例（`work/**/` のようなワイルドカードで既に覆われているもの）
    top = {p.name for p in root.iterdir() if p.is_dir()}
    others = {d for d in declared if '*' in d}
    missing = sorted(d for d in declared
                     if '*' not in d
                     and not d.startswith('.')
                     and d.split('/')[0] in top
                     and not matches(d, others)
                     and not (root / d).is_dir())

    res = residue(root)
    # 「古い／新しい」で線を引くと、前回のセッションが数時間前だっただけで
    # 見逃す。一時フォルダーは元々捨ててよい場所なので、溜まっていれば
    # 大きさにかかわらず毎回そのまま出して、消すかどうかは人に決めてもらう。
    total_mb = sum(r['mb'] for r in res)
    total_files = sum(r['files'] for r in res)
    total_tracked = sum(r['tracked'] for r in res)

    if md:
        print('### リポジトリの点検')
        print()
        print('**フォルダー**')
        print()
        if not unknown and not missing:
            print('CLAUDE.md の記載と実際のフォルダーは一致しています。')
            print()
        if unknown:
            print('**CLAUDE.md の表にないフォルダー**（知らないうちに増えたもの）')
            print()
            print('| フォルダー | 中のファイル数 |')
            print('|---|---|')
            for u in unknown:
                n = len(list((root / u).rglob('*')))
                print(f'| `{u}/` | {n} |')
            print()
            print('**表に追加するか、別の場所へ移すかをご判断ください。**')
            print()
        if missing:
            print('**CLAUDE.md にあるのに実在しないフォルダー**')
            print()
            for m in missing:
                print(f'- `{m}/`')
            print()
        print('**一時フォルダーの残骸**')
        print()
        if not res:
            print('ありません。')
        else:
            print(f'`work/` などの一時置き場に **{total_mb:.0f}MB / {total_files} ファイル** 溜まっています。')
            if not total_tracked:
                print('Git には入らないので、**消しても成果物は失われません**。')
            else:
                print(f'このうち **{total_tracked} ファイルは Git に入っています**。'
                      '消すと次のコミットで削除として記録されます。'
                      '一時置き場なら .gitignore で除外することをご検討ください。')
                if total_tracked < total_files:
                    print('それ以外は Git に入っていないので、消しても成果物は失われません。')
            print()
            if total_tracked:
                print('| 置き場 | ファイル数 | うち Git 管理 | 大きさ | 最終更新 |')
                print('|---|---|---|---|---|')
            else:
                print('| 置き場 | ファイル数 | 大きさ | 最終更新 |')
                print('|---|---|---|---|')
            for r in sorted(res, key=lambda r: -r['mb'])[:6]:
                age = f'{r["days"]*24:.0f}時間前' if r['days'] < 1 else f'{r["days"]:.0f}日前'
                git_col = f' {r["tracked"]} |' if total_tracked else ''
                print(f'| `{r["path"]}` | {r["files"]} |{git_col} {r["mb"]:.1f}MB | {age} |')
            if len(res) > 6:
                rest = sorted(res, key=lambda r: -r['mb'])[6:]
                git_col = f' {sum(x["tracked"] for x in rest)} |' if total_tracked else ''
                print(f'| （ほか {len(rest)} 件） | {sum(x["files"] for x in rest)} |{git_col}'
                      f' {sum(x["mb"] for x in rest):.1f}MB | |')
            print()
            print('**消してよいかご判断ください。**')
        print()
        return 1 if (unknown or missing) else 0

    print(f'リポジトリ: {root}')
    print(f'CLAUDE.md に書かれているフォルダー: {len(declared)} 件')
    print(f'実際に使われているフォルダー:       {len(actual)} 件')
    print()
    if unknown:
        print('⚠️  表にないフォルダー（知らないうちに増えたもの）')
        for u in unknown:
            n = len(list((root / u).rglob('*')))
            print(f'    {u}/   （中に {n} 件）')
        print()
    if missing:
        print('⚠️  表にあるのに実在しないフォルダー')
        for m in missing:
            print(f'    {m}/')
        print()
    if not unknown and not missing:
        print('✅ フォルダーは CLAUDE.md の記載と一致しています')
        print()
    if res:
        note = ('（Git 管理外。消しても成果物は残る）' if not total_tracked else
                f'（うち {total_tracked} ファイルは Git に入っている。消すと削除として記録される）')
        print(f'一時フォルダーの残骸: {total_mb:.0f}MB / {total_files} ファイル{note}')
        for r in sorted(res, key=lambda r: -r['mb'])[:6]:
            age = f'{r["days"]*24:.0f}時間前' if r['days'] < 1 else f'{r["days"]:.0f}日前'
            git_note = f'  うち Git {r["tracked"]}件' if r['tracked'] else ''
            print(f'    {r["path"]}   {r["files"]}件{git_note}  {r["mb"]:.1f}MB  {age}')
        if len(res) > 6:
            print(f'    …ほか {len(res)-6} 件')
        print()
    return 1 if (unknown or missing) else 0


if __name__ == '__main__':
    sys.exit(main())
