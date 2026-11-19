"""Full endpoint checks for selected native sites with many genuine domain bindings.

All native reads are paginated fake-aaPanel database queries. No host file,
running PHP, Nginx, DNS, or network target is modified or contacted.
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))

import ach_customizer_main as backend
import ach_customizer_vhost_drift as drift
import ach_customizer_cache_audit as cache
import ach_customizer_nginx_observation as nginx
import ach_customizer_hosts_manage as hosts_manage
from ach_customizer_hosts import native_site_snapshot


class LargeSelectedSiteEndpoints(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-selected-many-domains-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        state_patch = patch.object(backend, "_STATE_DIR", str(self.root))
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.plugin = backend.ach_customizer_main()
        self.site_reads = 0
        self.site_changed_after = None
        self.domains_changed_after = None
        self.db_rows = []
        self.set_domains(101)

    def set_domains(self, number):
        assert number >= 1
        self.db_rows = [
            {"id":i+1, "pid":7, "name":("site.test" if i == 0
             else f"alias{i:04d}-" + "a"*117 + ".test"), "port":80}
            for i in range(number)
        ]

    @staticmethod
    def flask():
        app = types.ModuleType("flask")
        app.has_request_context = lambda: True
        app.request = types.SimpleNamespace(method="POST")
        app.session = {"login":True,"uid":1}
        return app

    def public(self):
        out = types.ModuleType("public")
        outer = self

        class Query:
            def __init__(self, table):
                self.table = table
                self.offset = None
                self.page_size = None

            def where(self, expression, values):
                if self.table == "sites":
                    assert expression == "id=?" and tuple(values) == (7,)
                else:
                    assert expression == "pid IN (?)" and tuple(values) == (7,)
                return self

            def order(self, expression):
                assert self.table == "domain"
                assert expression == "pid asc, id asc"
                return self

            def limit(self, expression):
                assert self.table == "domain"
                self.offset,self.page_size = (int(v) for v in expression.split(","))
                assert self.page_size == 257
                return self

            def field(self, names):
                assert names == ("id,name,path,status" if self.table == "sites"
                                 else "id,pid,name,port")
                return self

            def find(self):
                assert self.table == "sites"
                outer.site_reads += 1
                name = ("reassigned.test" if outer.site_changed_after is not None
                        and outer.site_reads >= outer.site_changed_after
                        else "site.test")
                return {"id":7,"name":name,
                        "path":"/www/site.test","status":"1"}

            def select(self):
                assert self.table == "domain"
                result = [dict(row) for row in
                          outer.db_rows[self.offset:self.offset+self.page_size]]
                if outer.domains_changed_after is not None and (
                        outer.site_reads >= outer.domains_changed_after):
                    for row in result:
                        if row["id"] == len(outer.db_rows):
                            row["name"] = "new-binding.test"
                return result

        out.M = lambda table: Query(table)
        out.get_webserver = lambda: "nginx"
        out.get_panel_version = lambda: "8.1.0"
        return out

    def snapshot(self):
        site = {"id":7,"name":"site.test","path":"/www/site.test","status":"1",
                "bound_domains":[{"name":item["name"],"port":item["port"]}
                                 for item in self.db_rows]}
        return json.dumps(native_site_snapshot(site),ensure_ascii=False,
                          separators=(",",":"))

    def args(self):
        return {"site_id":"7","expected_site_key":"site.test",
                "expected_site_snapshot":self.snapshot(),
                "template":"404","locale":"en","site_delivery":"extension",
                "path":"/etc/shadow","domain":"attacker.example.test",
                "url":"http://attacker.invalid/"}

    def test_101_135_1001_bindings_survive_actual_hosts_vhost_cache_and_nginx_endpoints(self):
        for count in (101,135,1001):
            with self.subTest(count=count):
                self.set_domains(count)
                self.site_reads = 0
                args = self.args()
                if count == 1001:
                    self.assertGreater(len(args["expected_site_snapshot"]),110000)
                with (patch.dict(sys.modules,{"public":self.public(),"flask":self.flask()}),
                      patch.object(backend,"inspect_hosts_file",
                                   return_value={"state":"Local Loopback Entry",
                                                 "entries":[],"domains":[]}) as hosts_scan,
                      patch.object(hosts_manage,"inspect_recovery",
                                   return_value={"state":"None","recovery_id":None,"domain":None})):
                    response = self.plugin.inspect_local_hosts(args)
                self.assertTrue(response["status"],response)
                scanned = hosts_scan.call_args.args[0]
                self.assertEqual(len(scanned),count)
                self.assertEqual(scanned[0],"site.test")
                self.assertEqual(self.site_reads,3)
                self.site_reads=0
                with (patch.dict(sys.modules,{"public":self.public(),"flask":self.flask()}),
                      patch.object(drift,"inspect_vhost_drift",
                                   return_value={"state":"File Match"}) as vhost):
                    response=self.plugin.inspect_native_vhost(args)
                self.assertTrue(response["status"],response)
                self.assertEqual(len(vhost.call_args.args[1]["bound_domains"]),count)
                self.assertEqual(self.site_reads,3)
                self.site_reads=0
                with (patch.dict(sys.modules,{"public":self.public(),"flask":self.flask()}),
                      patch.object(cache,"inspect_site_fastcgi_cache",
                                   return_value={"state":"Source Observed","findings":[]}) as inspector,
                      patch("ach_customizer_cache_helper.inspect_nginx_helper_files",
                            return_value={"state":"Not Installed"})):
                    response=self.plugin.inspect_fastcgi_cache(args)
                self.assertTrue(response["status"],response)
                inspector.assert_called_once()
                self.assertEqual(self.site_reads,3)
                self.site_reads=0
                with (patch.dict(sys.modules,{"public":self.public(),"flask":self.flask()}),
                      patch.object(nginx,"observe_nginx_site",
                          return_value={"state":"Candidate Included",
                                        "origin_http":{"state":"No HTTP/80 Binding"},
                                        "reason":""}) as observer):
                    response=self.plugin.inspect_nginx_candidate(args)
                self.assertTrue(response["status"],response)
                self.assertEqual(len(observer.call_args.args[1]["bound_domains"]),count)
                self.assertEqual(self.site_reads,3)

    def test_1001_bindings_status_pages_selection_and_probe_are_supported(self):
        self.set_domains(1001)
        args=self.args()
        self.assertGreater(len(args["expected_site_snapshot"]),110000)
        key, decoded, original=self.plugin._status_probe_selection(args,7)
        self.assertEqual(key,"site.test")
        self.assertEqual(len(decoded[4]),1001)
        self.assertEqual(original,args["expected_site_snapshot"])
        probe_reply={"state":"Source Ready","runtime_verified":False}
        with (patch.dict(sys.modules,{"public":self.public(),"flask":self.flask()}),
              patch("ach_customizer_status_probe.probe_site_404",
                    return_value=probe_reply) as probe):
            response=self.plugin.status_probe(args)
        self.assertTrue(response["status"],response)
        self.assertEqual(response["state"],"Source Ready")
        self.assertEqual(len(probe.call_args.args[0]["bound_domains"]),1001)
        self.assertEqual(self.site_reads,3)

    def test_native_reassignment_and_changed_binding_revoke_large_selection(self):
        self.set_domains(135)
        args=self.args()
        for scenario in ("reassigned","changed-domain"):
            self.site_reads=0
            self.site_changed_after=3 if scenario=="reassigned" else None
            self.domains_changed_after=3 if scenario=="changed-domain" else None
            with (patch.dict(sys.modules,{"public":self.public(),"flask":self.flask()}),
                  patch.object(drift,"inspect_vhost_drift",
                      return_value={"state":"File Match"}) as inspector):
                result=self.plugin.inspect_native_vhost(args)
            self.assertFalse(result["status"],result)
            self.assertEqual(result["stage"],"website_vhost_inspection")
            if scenario=="reassigned":
                inspector.assert_called_once()
            else:
                inspector.assert_called_once()
        self.site_changed_after=None
        self.domains_changed_after=None

    def test_large_status_probe_rejects_mid_request_native_domain_reassignment(self):
        self.set_domains(1001)
        args=self.args()
        self.domains_changed_after=3
        with (patch.dict(sys.modules,{"public":self.public(),"flask":self.flask()}),
              patch("ach_customizer_status_probe.probe_site_404",
                  return_value={"state":"Source Ready","runtime_verified":False}) as probe):
            result=self.plugin.status_probe(args)
        self.assertFalse(result["status"],result)
        self.assertEqual(result["stage"],"status_probe")
        probe.assert_called_once()
        self.assertEqual(self.site_reads,3)

    def test_reassigned_site_id_is_rejected_before_any_vhost_read(self):
        self.set_domains(1001)
        args=self.args()
        native=self.public()
        original=native.M
        outer=self
        class ChangedSiteQuery:
            def where(self, *_): return self
            def field(self, *_): return self
            def find(self):
                outer.site_reads+=1
                return {"id":8,"name":"other.test",
                        "path":"/www/other.test","status":"1"}
        native.M=lambda table: ChangedSiteQuery() if table=="sites" else original(table)
        with (patch.dict(sys.modules,{"public":native,"flask":self.flask()}),
              patch.object(drift,"inspect_vhost_drift") as inspector):
            result=self.plugin.inspect_native_vhost(args)
        self.assertFalse(result["status"],result)
        self.assertEqual(result["stage"],"website_vhost_inspection")
        inspector.assert_not_called()

    def test_malformed_and_forged_large_selection_never_reaches_inspectors(self):
        self.set_domains(135)
        original=self.args()
        snapshots = [
            "x"*200000,
            "[]",
            json.dumps([7,"site.test","/www/site.test","1",[[42,"80"]]]),
            json.dumps([7,"site.test","/www/other","1",[]]),
        ]
        for value in snapshots:
            with self.subTest(sample=value[:14]):
                self.site_reads=0
                self.site_changed_after=None
                with (patch.dict(sys.modules,{"public":self.public(),"flask":self.flask()}),
                      patch.object(cache,"inspect_site_fastcgi_cache") as inspector):
                    result=self.plugin.inspect_fastcgi_cache(
                        {**original,"expected_site_snapshot":value})
                self.assertFalse(result["status"],result)
                inspector.assert_not_called()
