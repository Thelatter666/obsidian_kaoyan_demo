#!/usr/bin/env python3
"""零假阳性链接审计 —— 剥 ①注释块 ②围栏代码块 ③行内代码 后逐条对账。

用法：cd 到 vault 根目录（考研/），python3 管理/.audit.py
退出码：0 = 断链 0 条；1 = 有断链。

剥离规则按 CommonMark（Obsidian 同源）：
  ① 注释块      <!-- ... -->（可跨行）
  ② 围栏代码块  起始＝行首最多 3 空格 + 连续 ``` 或 ~~~ ≥3 + info string 不含同种围栏字符
                结束＝行首最多 3 空格 + 同种围栏字符且个数 ≥ 起始，其后仅空白
  ③ 行内代码    起始串与结束串反引号数必须『相等』；串内反引号按字面处理

为什么不用正则一次配对围栏（2026-10-12 R6 的教训）：
  正则 ``` `` ```.*?``` `` ``` 是任意配对，不符合「结束围栏反引号数 ≥ 起始」。
  某围栏块内含奇数个内联 ``` 提及且其后还有围栏块时，配对整体错位，
  围栏之后的正常正文被当代码吞掉 → 真断链漏报，脚本却报「通过」。
  故 ② 改为逐行状态机，且块内不做行内替换（块内嵌套反引号会误配正文）。
"""
import pathlib
import re
import sys

BT = chr(96)   # 反引号
TILDE = '~'

# 起始围栏：行首最多 3 空格 + 连续 3 个以上反引号或波浪号 + info string
FENCE_OPEN = re.compile(r' {0,3}(`{3,}|~{3,})(.*)$')
# 结束围栏：同上，但其后只能是空白
FENCE_CLOSE = re.compile(r' {0,3}(`{3,}|~{3,})[ \t]*$')


def strip_inline_code(text: str) -> str:
    """剥行内代码：起始串与结束串反引号数必须相等（CommonMark）。"""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] != BT:
            out.append(text[i])
            i += 1
            continue
        j = i
        while j < n and text[j] == BT:
            j += 1
        run = j - i
        k, closed = j, False
        while k < n:
            if text[k] != BT:
                k += 1
                continue
            m = k
            while m < n and text[m] == BT:
                m += 1
            if m - k == run:            # 等长串才算闭合
                out.append(' ' * run)
                i = m
                closed = True
                break
            k = m
        if not closed:                  # 没有闭合串 → 按字面保留
            out.append(text[i:j])
            i = j
    return ''.join(out)


def strip_contexts(text: str) -> str:
    # ① 注释块（可跨行）
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)

    # ②+③ 逐行：围栏块整体丢弃；只有非围栏行才剥行内代码
    out, fence, marker, inblock = [], 0, '', False
    for line in text.split('\n'):
        if inblock:
            m = FENCE_CLOSE.match(line)
            if m and m.group(1)[0] == marker and len(m.group(1)) >= fence:
                inblock = False
            continue                    # 块内（含结束行）一律丢弃
        m = FENCE_OPEN.match(line)
        if m and m.group(1)[0] not in m.group(2):   # info string 不得含同种围栏字符
            marker, fence, inblock = m.group(1)[0], len(m.group(1)), True
            continue
        out.append(strip_inline_code(line))
    return '\n'.join(out)


def audit_texts(pairs, extra_names=()):
    """pairs: [(文件名, 正文)] → (真链接数, 断链数, 断链清单[(文件, 目标)])。

    可解析目标集合＝各文件名的 stem（`[[2026-10-11-英语]]` 对应 `2026-10-11-英语.md`）。

    **2026-10-12 第二任修（假阳性）**：原实现只把 `.md` 收进 names，
    于是 `![[附件/xxx.jpg]]` 这类**附件嵌入**——哪怕文件真实存在——**一律被判断链**，
    且退出码 1。实测（造真附件 + 嵌入引用）：旧行为报「断链 2 条」退出 1，
    其中 1 条是**真实存在的附件**。
    修法：names 并入 `extra_names`（main 传入全库非 .md 文件的相对路径 stem 化前的完整相对路径）。
    注意 Obsidian 嵌入附件写的是**带目录的相对路径**，故 extra_names 用**相对路径本身**，
    同时兼容"只写文件名"的写法。
    """
    names = {pathlib.PurePath(name).stem for name, _ in pairs}
    names |= set(extra_names)
    # 兼容只写文件名（不带目录）的写法
    names |= {pathlib.PurePath(x).name for x in extra_names}
    tot = bad = 0
    hits = []
    for name, text in pairs:
        for m in re.finditer(r'\[\[([^\]]+)\]\]', strip_contexts(text)):
            tot += 1
            target = m.group(1).split('|')[0].split('#')[0].strip()
            if target not in names:
                bad += 1
                hits.append((name, target))
    return tot, bad, hits


def selftest() -> int:
    """内建回归测试：专打 R6 那个假阴性。

    造一份文档，围栏块内含奇数个内联围栏提及、其后还有围栏块、块后放 3 条断链。
    按 CommonMark 三条都该被抓到；用正则任意配对的旧实现只报得出 1 条。
    """
    fenced = '\n'.join([
        '# T',
        '',
        BT + 'text',
        '说明里提到 ' + BT + ' 这个围栏',
        BT,
        '',
        '正文：[[1999-02-02-真断链]] 和 [[1999-03-03-真断链2]]',
        '',
        BT + 'bash',
        'echo hi',
        BT,
        '',
        '再一条真断链：[[1999-04-04-真断链3]]',
    ])
    unclosed = '# U\n\n' + BT * 3 + 'text\nnever closed\n\nreal [[1999-01-01-X]]\n'
    tilde = '# T\n\n~~~\nfenced\n~~~\n\nreal [[1999-01-02-Y]]\n'
    # 数学辅导 2026-10-12 的用例：旧实现对它是 0/2（两条全吞）
    mt = '\n'.join([
        '# T',
        '',
        BT * 3 + 'bash',
        'echo hello',
        '# 提到 ' + BT * 3 + ' 一次',
        BT * 3,
        '真断链 [[1999-01-01-真断链]]。',
        '另一条真断链 [[1999-02-02-真断链2]]。',
        '',
        BT * 3 + 'bash',
        'echo world',
        BT * 3,
        '',
    ])

    # 2026-10-12 第二任加：附件嵌入假阳性回归。
    # 正文里 1 条真实附件嵌入 + 1 条真断链；只有把附件收进目标集合，
    # 才会得到 (2, 1)。旧实现（names 只收 .md）会报 (2, 2) —— 真附件被误判。
    embed = '\n'.join([
        '# E',
        '',
        '真附件嵌入：![[附件/2026-10-11-英语二-2012完形-题干.jpg]]',
        '',
        '真断链：[[1999-09-09-真断链]]',
    ])
    assets = ['附件/2026-10-11-英语二-2012完形-题干.jpg']

    cases = [
        ('围栏内奇数额外提及（R6）', [('T.md', fenced)], (3, 3)),
        ('块内 1 提及 + 后续围栏（数学辅导用例）', [('T.md', mt)], (2, 2)),
        ('未闭合围栏吞掉其后正文', [('U.md', unclosed)], (0, 0)),
        ('波浪号围栏', [('V.md', tilde)], (1, 1)),
        ('附件嵌入不算断链（假阳性回归）', [('E.md', embed)], (2, 1)),
    ]
    ok = True
    for label, pairs, (want_tot, want_bad) in cases:
        tot, bad, _ = audit_texts(pairs, extra_names=assets)
        good = (tot, bad) == (want_tot, want_bad)
        ok = ok and good
        print(f"  {'✓' if good else '✗'} {label}：真链接 {tot}/{want_tot}，断链 {bad}/{want_bad}")
    print(f"  自检{'通过' if ok else '失败'}——失败说明围栏剥离逻辑退化（R6 会复发）")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == '--selftest':
        return selftest()

    files = sorted(pathlib.Path('.').rglob('*.md'))
    # 附件等非 .md 文件也能作为嵌入/链接目标——不收进来会把真实附件误判为断链（假阳性）
    assets = [p.as_posix() for p in sorted(pathlib.Path('.').rglob('*'))
              if p.is_file() and p.suffix != '.md']
    # 每项是 (链接目标名, 正文)——目标名用 stem，与 [[...]] 里的写法对齐
    pairs = [(p.stem, p.read_text(encoding='utf-8')) for p in files]
    tot, bad, hits = audit_texts(pairs, extra_names=assets)
    for name, target in hits:
        print(f"  ✗ 断链 [[{target}]] @ {name}.md")
    print(f"  真链接 {tot} 条，断链 {bad} 条 → {'通过' if bad == 0 else '要修'}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
