from sqlalchemy import select


async def test_create_run_persists_to_db(db_engine, monkeypatch):
    import importlib

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.db.models.run import RunORM
    from core.run_manager import RunManager

    db_engine_module = importlib.import_module("core.db.engine")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(db_engine_module, "async_session_factory", factory)

    manager = RunManager()
    run = await manager.create_run(
        owner_user_id="user-1",
        request_messages=[{"role": "user", "content": "hello"}],
    )

    async with factory() as session:
        result = await session.execute(select(RunORM).where(RunORM.id == run.id))
        orm = result.scalar_one()

    assert orm.owner_user_id == "user-1"
    assert orm.status == "running"


async def test_append_event_increments_sequence(db_engine, monkeypatch):
    import importlib

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.run_manager import RunManager

    db_engine_module = importlib.import_module("core.db.engine")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(db_engine_module, "async_session_factory", factory)

    manager = RunManager()
    run = await manager.create_run(owner_user_id="user-1", request_messages=[])

    await manager.append_event(run.id, "request.received", {"message_count": 1})
    await manager.append_event(run.id, "response.completed", {"content": "done"})

    reloaded = await manager.get_run(run.id, owner_user_id="user-1")

    assert [event.seq for event in reloaded.events] == [0, 1]
    assert [event.event_type for event in reloaded.events] == [
        "request.received",
        "response.completed",
    ]


async def test_finish_run_updates_status_and_response(db_engine, monkeypatch):
    import importlib

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.run_manager import RunManager

    db_engine_module = importlib.import_module("core.db.engine")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(db_engine_module, "async_session_factory", factory)

    manager = RunManager()
    run = await manager.create_run(owner_user_id="user-1", request_messages=[])

    await manager.finish_run(
        run.id,
        status="completed",
        response_payload={"choices": [{"message": {"content": "ok"}}]},
    )

    reloaded = await manager.get_run(run.id, owner_user_id="user-1")

    assert reloaded.status == "completed"
    assert reloaded.finished_at is not None
    assert reloaded.response_payload["choices"][0]["message"]["content"] == "ok"
