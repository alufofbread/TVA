import io
import json
import logging
import unittest
from unittest.mock import patch
from bot import RailwayLogFormatter, configure_logging


class RuntimeLoggingTests(unittest.TestCase):
    def test_queue_logs_use_single_structured_stdout_handler(self):
        root=logging.getLogger();report=logging.getLogger('aether.website_sync')
        old_handlers=root.handlers[:];old_level=root.level
        report_handlers=report.handlers[:];propagate=report.propagate
        try:
            output=io.StringIO()
            with patch('sys.stdout',output):
                configure_logging()
                import importlib, website_sync
                importlib.reload(website_sync)
                report.info('queue healthy')
                logging.warning('needs attention')
            lines=output.getvalue().splitlines()
            self.assertEqual([json.loads(line)['level'] for line in lines],['info','warn'])
        finally:
            root.handlers=old_handlers;root.setLevel(old_level)
            report.handlers=report_handlers;report.propagate=propagate

    def test_errors_keep_tracebacks_inside_one_json_entry(self):
        try:raise RuntimeError('fixture failure')
        except RuntimeError:
            import sys
            record=logging.LogRecord('aether',logging.ERROR,'',1,'failed',(),sys.exc_info())
            encoded=RailwayLogFormatter().format(record)
        self.assertNotIn('\n',encoded)
        self.assertEqual(json.loads(encoded)['level'],'error')
        self.assertIn('RuntimeError: fixture failure',json.loads(encoded)['message'])
