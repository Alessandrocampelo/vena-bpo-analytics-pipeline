"""Sensor de falha do job de scraping — dispara quando o RetryPolicy esgota
as tentativas e a run falha de verdade. Loga um alerta estruturado; sem
canal real de Slack/e-mail no escopo do teste (ADR-006) — hook pronto
para plugar num canal real depois."""

from dagster import RunFailureSensorContext, run_failure_sensor

from dagster_project.jobs import scraping_job


@run_failure_sensor(monitored_jobs=[scraping_job])
def scraping_failure_alert(context: RunFailureSensorContext) -> None:
    context.log.error(
        "ALERTA: job de scraping (%s) falhou após esgotar o retry policy — run_id=%s. Erro: %s"
        % (
            context.dagster_run.job_name,
            context.dagster_run.run_id,
            context.failure_event.message,
        )
    )
