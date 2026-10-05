# 原生生成资产：开发审阅样本（质量未通过）

以下正文未经修订，保留错误供复核；不是经验证的实施建议，不应据此执行。来源哈希及真实失败依据见 native-skill-window-real-outcome-20261005.json。

---

---
name: django-simple-tag-kwonly-default-fix
description: 修复 Django simple_tag / inclusion_tag 对 keyword-only 参数（带默认值或重复传参）报错错误的问题：定位 parse_bits 的 unhandled_kwargs 与 kwonly_defaults 关系，附复现脚本、验证步骤与陷阱。
---

# Django 模板 custom tag keyword-only 参数解析修复

## 何时使用
- 在 Django（/workspace checkout，Python 3.6 testbed）中处理类似 "Custom template tags raise TemplateSyntaxError when keyword-only arguments with defaults are provided" 的 issue。
- `@register.simple_tag` 或 `@register.inclusion_tag` 的函数签名形如 `def hello(*, greeting='hello')`，模板里 `{% hello greeting="hi" %}` 或 `{% hello greeting="a" greeting="b" %}` 报出错误信息（`received unexpected keyword argument`）与期望不符。
- 定位到 `django/template/library.py` 的 `parse_bits` 函数（simple_tag 和 inclusion_tag 共用）。

## 关键代码位置
- `django/template/library.py`：
  - `simple_tag` / `inclusion_tag` 装饰器 → 调 `getfullargspec(unwrap(func))` 拿到 `params, varargs, varkw, defaults, kwonly, kwonly_defaults`。
  - `parse_bits(parser, bits, params, varargs, varkw, defaults, kwonly, kwonly_defaults, takes_context, name)` 是唯一入口，simple/inclusion 共用。
- `django/template/base.py`：
  - `kwarg_re = r"(?:(\w+)=)?(.+)"`
  - `token_kwargs(bits, parser, support_legacy=False)`：对单个 bit 做 kwarg 抽取，`support_legacy` 默认 False 时只接受 `name=value` 形式。
- 现有测试用例：
  - `tests/template_tests/templatetags/custom.py` 中 `simple_keyword_only_param(*, kwarg)` 与 `simple_keyword_only_default(*, kwarg=42)`。
  - `tests/template_tests/test_custom.py` 已有针对两者的正向/缺失用例，以及 `received multiple values for keyword argument` 的 unlimited_args_kwargs 用例。

## 核心问题（观察到的根因）
`parse_bits` 中的 `unhandled_kwargs` 只包含"没有默认值的 keyword-only 参数"：
```python
unhandled_kwargs = [
    kwarg for kwarg in kwonly
    if not kwonly_defaults or kwarg not in kwonly_defaults
]
```
对 `def hello(*, greeting='hello')`：`kwonly=['greeting']`、`kwonly_defaults={'greeting':'hello'}` → `unhandled_kwargs=[]`。

循环内对 kwarg 的判定顺序为：
```python
if param not in params and param not in unhandled_kwargs and varkw is None:
    # "received unexpected keyword argument"
elif param in kwargs:
    # "received multiple values for keyword argument"
```
于是：
- 情况 B（`greeting="hi"` 有默认值）：`greeting ∉ params`、`greeting ∉ unhandled_kwargs`、`varkw is None` → 命中"unexpected keyword argument"，而不是应该走 `elif param in kwargs`（未重复）落入 else 分支记入 kwargs。
- 情况 C（`greeting="hi" greeting="hello"` 无默认值重复传）：`greeting ∈ unhandled_kwargs` → 第一条 if 不成立，进入 `elif param in kwargs` → 命中 "multiple values"。这条分支本身逻辑正确，但由于 `if` 分支先于 `elif` 评估，重复传参且参数"恰好有默认值"时会先被"unexpected"截胡。

期望行为：先判"重复"（`param in kwargs`），再判"unknown"（不在 params / unhandled_kwargs / varkw），最后正常记录。

## 参考修复
把 `parse_bits` 里 kwarg 分支的判定顺序调整为"先判重复、再判 unknown"：
```python
if param in kwargs:
    raise TemplateSyntaxError(
        "'%s' received multiple values for keyword argument '%s'" % (name, param))
elif param not in params and param not in unhandled_kwargs and varkw is None:
    raise TemplateSyntaxError(
        "'%s' received unexpected keyword argument '%s'" % (name, param))
```
（仅调整 if / elif 顺序；其余 `kwargs[str(param)] = value` 与 `unhandled_*` 消费逻辑不变。）

> 说明：仅调整顺序能修好"重复传 keyword-only 参数"的错误信息（情况 C / H）。若还需修"有默认值的 keyword-only 参数首次传入被报 unexpected"（情况 B / G），还需把 `unhandled_kwargs` 的判定改为包含有默认值的 kwonly，或在 if 中显式加入 `param not in (kwonly or [])` 的放行分支。本次会话仅完成顺序调整，**未观察到 B/G 在顺序调整后通过的最终证据**（最后一次直接调用 `parse_bits` 仍报 unexpected）。落地时务必补上对"有默认值 kwonly 首次传入"的放行，并以完整回归为验收。

## 复现脚本（观察到的）
`/tmp/mytags/testlib.py`：
```python
from django import template
register = template.Library()

@register.simple_tag
def hello(*, greeting='hello'):
    return f'{greeting} world'

@register.simple_tag
def hi(*, greeting):
    return f'{greeting} world'

@register.inclusion_tag('mytags_incl.html')
def inc(*, greeting='hello'):
    return {'greeting': greeting}
```
`/tmp/mytags_incl.html`：`INCL: {{ greeting }} world`

复现入口（settings.configure 必须带 `OPTIONS.libraries`，不能把 `Library` 对象直接塞 `Engine(libraries=...)`）：
```python
import sys; sys.path.insert(0, '/tmp')
from django.conf import settings
settings.configure(TEMPLATES=[{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': ['/tmp'], 'APP_DIRS': False,
    'OPTIONS': {'libraries': {'testlib': 'mytags.testlib'}},
}])
import django; django.setup()
from django.template import Template, Context
print(Template('{% load testlib %}{% hello greeting="hi" %}').render(Context()))
```

## 验证步骤
1. 跑复现脚本确认各 case 基线（A no-kw / B kw w/ default / C dup / D missing / E kw w/o default / F bad kw / G-H-I inclusion 对应）。
2. 应用顺序调整后复跑同一脚本；用 `expected in str(e)` 或精确匹配断言。
3. 直接调用 `parse_bits` 做隔离验证：
   ```python
   from django.template.library import parse_bits
   from django.template import base
   p = base.Parser(list(base.Lexer("x").tokenize()))
   parse_bits(p, ['greeting="hi"'], [], None, None, None,
              ['greeting'], {'greeting': 'hello'}, False, 'hello')
   ```
4. 跑仓库自带回归：
   ```bash
   cd /workspace && python tests/runtests.py template_tests.test_custom
   cd /workspace && python tests/runtests.py template_tests
   ```
5. 若仓库有对应 `docs/releases/*.txt`，按 Django 规范补 changelog 条目（本次会话 grep 未找到现成条目）。

## 陷阱 / 已观察到的坑
- **Engine 的 `libraries` 参数只接受字符串路径**：`Engine(libraries={'t': lib})`（lib 是 `Library` 实例）会触发 `AttributeError: 'Library' object has no attribute 'startswith'`。正确做法是 `settings.configure(TEMPLATES=[{...'OPTIONS': {'libraries': {'name': 'pkg.mod'}}}])`，让 `import_library` 走 `import_module`。
- **DjangoTemplates 后端构造**：`DjangoTemplates({...})` 期望参数里带 `OPTIONS` key，否则 `KeyError: 'OPTIONS'`。直接用 `settings.TEMPLATES` + `django.setup()` 更稳。
- **`base.Parser` 构造**：本仓库版本签名为 `Parser(tokens, libraries=None, builtins=None, origin=None)`，**不接受 engine 参数**；`Lexer(template_string)` 也**不接受 engine**。隔离调用时按 `Parser(list(Lexer("x").tokenize()))` 走。
- **`token_kwargs` 只处理单个 bit**：对 `bits=[bit]` 调用，返回 `{key: FilterExpression}`；`support_legacy=False` 时不识别 `as` 形式。
- **`getfullargspec` 的 `kwonly_defaults` 可能是 None**（无默认值的 kwonly），构造 `unhandled_kwargs` 时 `not kwonly_defaults` 短路保护，不要把 None 当 dict 用。
- **`parse_bits` 是 simple_tag 和 inclusion_tag 共用入口**：修一次两处都生效，测试要同时覆盖 `{% simple ... %}` 和 `{% inclusion ... %}` 两条路径。
- **`as` 目标变量**：simple_tag 支持 `tag ... as var`，装饰器在调 `parse_bits` 前已把 `as var` 两个 bit 剥掉；不要把这个剥除逻辑和 kwarg 解析混在一起改。

## 证据（本次会话观察）
- 观察到基线 `parse_bits` 源码（行号 237-309），`unhandled_kwargs` 定义在 254-257，判定 if/elif 在 264-273。
- 复现脚本在顺序调整前跑出：A `'hello world'`、B `received unexpected keyword argument 'greeting'`、C 同 B、D `did not receive value(s)`、E `'yo world'`、F `received unexpected keyword argument 'nope'`、G/H 同 B、I 同 F。
- 顺序调整（if/elif 互换）后的复跑：C/H 变为 `received multiple values for keyword argument`（OK），B/G 仍为 `received unexpected keyword argument`（MISMATCH），直接 `parse_bits` 调用也仍报 unexpected。
- 现有测试 `tests/template_tests/test_custom.py:61-64` 覆盖 `simple_keyword_only_param kwarg=37` 与 `simple_keyword_only_default`（无参默认 42）；未观察到本次修改后 `runtests.py template_tests.test_custom` 的最终结果（转录截断）。
- 仓库 git 基线为 `133ece9 Pilot task baseline`，工作区在 patch 应用后仅 `django/template/library.py` 有 diff。

## 未验证 / 落地注意
- 本次会话**未观察到 `runtests.py template_tests` 全绿**的最终运行结果；顺序调整只解决了"重复传 keyword-only 参数"的错误信息。
- "有默认值的 kwonly 首次传入被报 unexpected"（B/G）需要额外放行（如把 `unhandled_kwargs` 改为全部 kwonly，或在 unknown 判定里加入 `param not in (kwonly or [])`）；落地后必须以 `python tests/runtests.py template_tests` 通过为验收标准。
- 修复后建议同步补 `tests/template_tests/test_custom.py` 中：
  - `{% simple_keyword_only_default kwarg=7 %}` → `simple_keyword_only_default - Expected result: 7`
  - `{% simple_keyword_only_param kwarg=1 kwarg=2 %}` → `received multiple values for keyword argument 'kwarg'`
  - 以及对应的 inclusion_tag 用例。
- 按 Django 规范在 `docs/releases/` 对应版本文件补 `Bugfixes` 条目。
