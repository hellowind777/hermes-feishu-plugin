from hermes_feishu_plugin.core.i18n import localize_system_text


def test_localize_dynamic_skill_created_message(monkeypatch):
    monkeypatch.setenv("HERMES_FEISHU_LOCALE", "zh_cn")
    assert (
        localize_system_text("💾 Skill 'a-share-holdings-screenshot-analysis' created.")
        == "💾 已创建技能「a-share-holdings-screenshot-analysis」。"
    )


def test_localize_dynamic_cron_created_message(monkeypatch):
    monkeypatch.setenv("HERMES_FEISHU_LOCALE", "zh_cn")
    assert (
        localize_system_text("💾 Cron job 'stock-preopen-brief' created.")
        == "💾 已创建定时任务「stock-preopen-brief」。"
    )


def test_localize_gateway_shutdown_notice(monkeypatch):
    monkeypatch.setenv("HERMES_FEISHU_LOCALE", "zh_cn")
    assert (
        localize_system_text("⚠️ Gateway shutting down — Your current task will be interrupted.")
        == "⚠️ 网关正在关闭——当前任务将被中断。"
    )
