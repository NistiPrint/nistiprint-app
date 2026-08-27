import sys
from pathlib import Path
from unittest import TestCase


WORKER_DIR = Path(__file__).resolve().parents[1]
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

import celery_config  # noqa: E402


class CeleryConfigTest(TestCase):
    def test_default_schedules_use_unified_app_managed_renewal_task(self):
        schedules = celery_config.get_default_schedules()

        self.assertIn("renew-app-managed-credentials", schedules)
        self.assertEqual(
            schedules["renew-app-managed-credentials"]["task"],
            "tasks.token_renewal_tasks.renew_app_managed_credentials",
        )
        self.assertEqual(
            schedules["renew-app-managed-credentials"]["schedule"],
            7200,
        )
        self.assertNotIn("renew-shopee-tokens", schedules)
        self.assertNotIn("sync-firestore-tokens", schedules)

    def test_default_schedules_include_daily_personalization_batch(self):
        schedules = celery_config.get_default_schedules()

        entrada = schedules["processar-personalizados-diario"]
        self.assertEqual(entrada["task"], "services.ai_personalization.processar_pendentes")
        self.assertEqual(entrada["options"], {"queue": "ai_personalization"})


class BuildScheduleTest(TestCase):
    """O agendador precisa distinguir 'de tempos em tempos' de 'nesse horario'.

    Antes existia so `schedule_seconds`, e o lote diario de personalizados nao
    cabe nessa forma: um intervalo de 86400 deriva a cada reinicio do beat ate
    que 'meio-dia' vire madrugada. Estes casos travam a traducao das duas
    formas e, principalmente, o que acontece quando a configuracao esta errada.
    """

    def _cron_repr(self, schedule):
        return celery_config.describe_schedule(schedule)

    def test_cron_dict_agenda_no_horario(self):
        schedule = celery_config.build_schedule("diario", {"cron": {"hour": 12, "minute": 0}})
        self.assertEqual(self._cron_repr(schedule), "cron 0 12 * * *")

    def test_cron_em_texto_de_cinco_campos(self):
        schedule = celery_config.build_schedule("diario", {"cron": "0 12 * * *"})
        self.assertEqual(self._cron_repr(schedule), "cron 0 12 * * *")

    def test_hora_sem_minuto_vira_minuto_zero(self):
        # O default do Celery para `minute` e `*`: sem esta normalizacao,
        # "as 12h" viraria sessenta disparos entre 12:00 e 12:59.
        schedule = celery_config.build_schedule("diario", {"cron": {"hour": 12}})
        self.assertEqual(self._cron_repr(schedule), "cron 0 12 * * *")

    def test_cron_tem_precedencia_sobre_intervalo(self):
        schedule = celery_config.build_schedule(
            "diario", {"cron": {"hour": 12, "minute": 0}, "schedule_seconds": 60},
        )
        self.assertEqual(self._cron_repr(schedule), "cron 0 12 * * *")

    def test_intervalo_continua_funcionando(self):
        self.assertEqual(celery_config.build_schedule("t", {"schedule_seconds": 300}), 300)

    def test_cron_invalido_nao_agenda_em_vez_de_cair_no_default(self):
        # Cair no intervalo default faria uma task diaria rodar de minuto em
        # minuto sem ninguem perceber — pior que nao agendar.
        for config in (
            {"cron": {"hour": 99, "minute": 0}},
            {"cron": "0 12 *"},
            {"cron": {"campo_inexistente": 1}},
            {"schedule_seconds": "abc"},
        ):
            with self.subTest(config=config):
                self.assertIsNone(celery_config.build_schedule("t", config))
