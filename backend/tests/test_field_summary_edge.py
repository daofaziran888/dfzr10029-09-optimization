"""字段分区摘要服务级边界验收（独立实例，不依赖 HTTP 服务）。"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.field_summary import FieldSummaryService


def assert_true(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"ok: {msg}")


svc = FieldSummaryService()
svc.register_dataset(99, "DATA-T")

base = [
    {"分区编号": "p1", "分区类型": "daily", "分区完成时间": "2026-11-16 02:00:00",
     "字段名称": "f1", "字段类型": "string"},
    {"分区编号": "p1", "分区类型": "daily", "分区完成时间": "2026-11-16 02:00:00",
     "字段名称": "f2", "字段类型": "bigint"},
    {"分区编号": "p2", "分区类型": "daily", "分区完成时间": "2026-11-17 02:00:00",
     "字段名称": "f1", "字段类型": "string"},
    {"分区编号": "p2", "分区类型": "daily", "分区完成时间": "2026-11-17 02:00:00",
     "字段名称": "f3", "字段类型": "datetime"},
]
svc.seed_partitions(99, copy.deepcopy(base))

# 首轮：两个分区全部建立，字段注册表按首次出现顺序 f1 f2 f3
v1 = svc.refresh(99)
assert_true(v1["current_version"] == 1 and len(v1["changed_partitions"]) == 2, "首轮两个分区都建摘要")
assert_true(v1["field_order"] == ["f1", "f2", "f3"], "字段顺序按首次出现位置固定")

# 无变化刷新
v2 = svc.refresh(99)
assert_true(v2["changed_partitions"] == [], "无变化刷新没有变化分区")

# 下线 p2：变化一次
svc.seed_partitions(99, [row for row in base if row["分区编号"] == "p1"])
v3 = svc.refresh(99)
assert_true([p["分区编号"] for p in svc.get_view(99)["partition_summaries"] if p.get("分区状态") == "已下线"] == ["p2"],
            "消失分区被标记为已下线")
assert_true([p["分区编号"] for p in v3["changed_partitions"]] == ["p2"], "下线只在当轮计入变化分区")
v4 = svc.refresh(99)
assert_true(v4["changed_partitions"] == [], "已下线分区不会在后续刷新重复显示")
assert_true(len([p for p in v4["partition_summaries"] if p.get("分区状态") == "已下线"]) == 1,
            "已下线分区仍保留在视图中可回查")

# 待核对项按当前版本统计：p2 重新上线产生待办；后续刷新只保留本轮变化的待办，
# 未核对记录随旧版本整体归档，不会在当前视图重复堆积。
svc.seed_partitions(99, copy.deepcopy(base))
v5 = svc.refresh(99)  # p2 重新出现
assert_true(len(v5["pending_reconciles"]) >= 1, "分区重新上线产生待核对项")
archived_p2 = [p for p in svc.get_version(99, v5["current_version"])["pending_reconciles"]
               if p["分区编号"] == "p2"]
assert_true(len(archived_p2) == 1 and archived_p2[0]["版本"] == v5["current_version"],
            "未核对的待办随版本归档保留，可按版本回查")
drifted = [
    {"分区编号": "p1", "分区类型": "daily", "分区完成时间": "2026-11-18 02:00:00",
     "字段名称": "f1", "字段类型": "string"},
    {"分区编号": "p1", "分区类型": "daily", "分区完成时间": "2026-11-18 02:00:00",
     "字段名称": "f2", "字段类型": "bigint"},
    {"分区编号": "p1", "分区类型": "daily", "分区完成时间": "2026-11-18 02:00:00",
     "字段名称": "f4", "字段类型": "string"},
    # p2 保持内容不变，验证它不会被重复计入变化
    {"分区编号": "p2", "分区类型": "daily", "分区完成时间": "2026-11-17 02:00:00",
     "字段名称": "f1", "字段类型": "string"},
    {"分区编号": "p2", "分区类型": "daily", "分区完成时间": "2026-11-17 02:00:00",
     "字段名称": "f3", "字段类型": "datetime"},
]
svc.seed_partitions(99, drifted)
v6 = svc.refresh(99)
assert_true(v6["field_order"] == ["f1", "f2", "f3", "f4"], "新字段 f4 追加队尾，老字段位置不变")
assert_true([p["分区编号"] for p in v6["pending_reconciles"]] == ["p1"],
            "新一轮待核对项只包含本轮变化分区，旧待办不重复堆积")

# 类型变更检测
drifted2 = [
    {"分区编号": "p1", "分区类型": "daily", "分区完成时间": "2026-11-19 02:00:00",
     "字段名称": "f1", "字段类型": "varchar(64)"},
    {"分区编号": "p1", "分区类型": "daily", "分区完成时间": "2026-11-19 02:00:00",
     "字段名称": "f2", "字段类型": "bigint"},
    {"分区编号": "p1", "分区类型": "daily", "分区完成时间": "2026-11-19 02:00:00",
     "字段名称": "f4", "字段类型": "string"},
]
svc.seed_partitions(99, drifted2)
v7 = svc.refresh(99)
p1 = [p for p in v7["changed_partitions"] if p["分区编号"] == "p1"][0]
assert_true(p1["changes"]["type_changed"] == [{"字段名称": "f1", "原类型": "string", "新类型": "varchar(64)"}],
            "字段类型变更被准确识别")
assert_true(v7["field_order"] == ["f1", "f2", "f3", "f4"], "类型变更不改变字段顺序")

# 强制全量重建（changed_only=False）：所有分区都重建，版本仍只提交一份
v8 = svc.refresh(99, changed_only=False)
assert_true(len(v8["changed_partitions"]) == 1, "强制重建覆盖当前所有分区")
assert_true(svc.get_view(99)["current_version"] == v8["current_version"], "任意刷新都只保留一份当前有效版本")

# 核对冲突唯一性：连续三次不同结论，历史里同分区同版本只有一条
svc.reconcile(99, "p1", "核对通过", remark="第一次")
svc.reconcile(99, "p1", "核对驳回", remark="第二次")
svc.reconcile(99, "p1", "冲突待裁决", remark="第三次")
view = svc.get_view(99)
same = [h for h in view["reconcile_history"] if h["分区编号"] == "p1" and h["版本"] == view["current_version"]]
assert_true(len(same) == 1 and same[0]["核对状态"] == "冲突待裁决" and same[0]["核对说明"] == "第三次",
            "同分区同版本多次核对冲突后只剩唯一有效结果")

# 非法核对结果被拒
try:
    svc.reconcile(99, "p1", "随便写")
    raise AssertionError("非法核对结果应被拒绝")
except ValueError:
    print("ok: 非法核对结果被拒绝")

# 版本回查链完整
versions = svc.list_versions(99)
assert_true([v["版本"] for v in versions] == list(range(1, 9)), "八个版本全部保留可回查")
assert_true(svc.get_version(99, 1)["field_order"] == ["f1", "f2", "f3"], "v1 回查字段顺序与当时一致")

# 概览聚合
ov = svc.overview()
assert_true(ov["摘要数据集"] == 1 and ov["分区总数"] >= 1 and ov["待核对项"] == 0,
            "概览正确聚合分区量，核对完成后待核对项归零")

print("\n服务级边界验收全部通过")
