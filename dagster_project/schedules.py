"""Schedule diário — cobre o requisito de "dashboard diário" do enunciado."""

from dagster import ScheduleDefinition

from dagster_project.jobs import daily_raw_job

daily_schedule = ScheduleDefinition(
    job=daily_raw_job,
    cron_schedule="0 6 * * *",
    execution_timezone="America/Sao_Paulo",
)
