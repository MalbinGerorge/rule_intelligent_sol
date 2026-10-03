# Sigma Generation Trace

## Rule 527 (correlation)

```json
{
  "base_title": "FortiGate SSL VPN Failed Login (User Present)",
  "base_description": "Detects a single Fortinet FortiGate SSL VPN login failure event where the username field is present (not 'N/A'), excluding events from source IPs contained in an environment-specific blocked/exclusion reference set.",
  "base_status": "test",
  "base_level": "medium",
  "base_logsource": {
    "category": "authentication",
    "product": "fortigate",
    "service": null
  },
  "base_detection": {
    "selections": [
      {
        "name": "selection",
        "field_values": [
          {
            "field": "QID",
            "modifier": null,
            "values": [
              "20257911"
            ]
          },
          {
            "field": "Username",
            "modifier": null,
            "values": [
              "N/A"
            ]
          }
        ]
      },
      {
        "name": "filter_excluded_src_ip_refset",
        "field_values": [
          {
            "field": "SourceIP",
            "modifier": null,
            "values": [
              "an environment-specific IP address list used as an exclusion/blocked reference set; typically a mix of IPv4 dotted-quad addresses (four 1–3 digit octets separated by '.'), e.g. '<octet>.<octet>.<octet>.<octet>'"
            ]
          }
        ]
      }
    ],
    "condition": "selection and not filter_excluded_src_ip_refset"
  },
  "base_tags": [
    "attack.credential_access",
    "attack.t1110"
  ],
  "reference_name": "fortigate_ssl_vpn_failed_login_user_present",
  "correlation_title": "FortiGate SSL VPN Slow Brute Force - Multiple Failed Logins From Same Username",
  "correlation_description": "Triggers when 6 or more FortiGate SSL VPN login failures occur for the same username within 5 minutes (slow brute force), excluding source IPs in an environment-specific exclusion list.",
  "correlation_status": "test",
  "correlation_level": "high",
  "correlation": {
    "type": "event_count",
    "rules": [
      "fortigate_ssl_vpn_failed_login_user_present"
    ],
    "group_by": [
      "Username"
    ],
    "timespan": "5m",
    "condition": {
      "operator": "gte",
      "count": 6,
      "field": null
    }
  },
  "correlation_tags": [
    "attack.credential_access",
    "attack.t1110"
  ],
  "correlation_falsepositives": [
    "User repeatedly mistyping credentials",
    "Automated health checks or misconfigured clients repeatedly attempting authentication",
    "Password reset / account lockout testing activity by administrators"
  ],
  "mitre_techniques_inferred": [
    {
      "tactic": "Credential Access",
      "technique_id": "T1110",
      "technique_name": "Brute Force",
      "confidence": "high"
    }
  ]
}
```

---

## Rule 815 (standalone)

```json
{
  "title": "UAC bypass via fodhelper.exe parent process (Windows Security)",
  "description": "Detects potential User Account Control (UAC) bypass activity where a process creation-related event indicates the parent process name contains 'fodhelper.exe'. This is based on Windows Security Event Log process creation telemetry (Event ID 4688) and related process/script execution telemetry (Event IDs 1, 4104) as implemented in the originating QRadar rule.",
  "status": "stable",
  "level": "high",
  "logsource": {
    "category": "process_creation",
    "product": "windows",
    "service": "security"
  },
  "detection": {
    "selections": [
      {
        "name": "selection_event_ids",
        "field_values": [
          {
            "field": "EventID",
            "modifier": null,
            "values": [
              "1",
              "4104",
              "4688"
            ]
          }
        ]
      },
      {
        "name": "selection_parent_fodhelper",
        "field_values": [
          {
            "field": "ParentImage",
            "modifier": "contains",
            "values": [
              "fodhelper.exe"
            ]
          }
        ]
      }
    ],
    "condition": "selection_event_ids and selection_parent_fodhelper"
  },
  "tags": [
    "attack.privilege-escalation",
    "attack.t1548",
    "attack.t1548.002"
  ],
  "falsepositives": [
    "Legitimate administrative or troubleshooting activity that launches processes via fodhelper.exe (rare).",
    "Security testing or red team activity simulating UAC bypass techniques."
  ],
  "mitre_techniques_inferred": []
}
```

---

## Rule 930 (standalone)

```json
{
  "title": "Suspicious Access to Browser Credential Storage Files",
  "description": "Detects Windows Security auditing file access events (Event ID 4663) where the accessed object path indicates common browser profile locations and credential/cookie storage artifacts (e.g., Login Data, Cookies, WebCache) with database/JSON extensions. This may indicate credential theft from browser stores (T1555.003).",
  "status": "stable",
  "level": "medium",
  "logsource": {
    "category": "file_event",
    "product": "windows",
    "service": "security"
  },
  "detection": {
    "selections": [
      {
        "name": "selection_eventid",
        "field_values": [
          {
            "field": "EventID",
            "modifier": null,
            "values": [
              "4663"
            ]
          }
        ]
      },
      {
        "name": "selection_browser_path_fragments",
        "field_values": [
          {
            "field": "ObjectName",
            "modifier": "contains",
            "values": [
              "\\Sputnik\\Sputnik",
              "\\MapleStudio\\ChromePlus",
              "\\QIP Surf",
              "\\Google\\Chrome",
              "\\Chromium",
              "\\GhostBrowser",
              "\\360Browser\\Browser",
              "\\360Chrome\\Chrome",
              "\\Comodo\\Dragon",
              "\\BraveSoftware\\Brave-Browser",
              "\\Microsoft\\Edge",
              "\\Mozilla\\SeaMonkey\\"
            ]
          }
        ]
      },
      {
        "name": "selection_profile_location",
        "field_values": [
          {
            "field": "ObjectName",
            "modifier": "contains",
            "values": [
              "\\Profiles\\",
              "\\User Data"
            ]
          }
        ]
      },
      {
        "name": "selection_credential_artifacts",
        "field_values": [
          {
            "field": "ObjectName",
            "modifier": "contains",
            "values": [
              "\\Login Data",
              "\\Cookies",
              "\\EncryptedStorage",
              "\\WebCache"
            ]
          }
        ]
      },
      {
        "name": "selection_extensions",
        "field_values": [
          {
            "field": "ObjectName",
            "modifier": "contains",
            "values": [
              ".db",
              ".sqlite",
              ".json"
            ]
          }
        ]
      }
    ],
    "condition": "selection_eventid and selection_browser_path_fragments and selection_profile_location and selection_credential_artifacts and selection_extensions"
  },
  "tags": [
    "attack.credential-access",
    "attack.t1555",
    "attack.t1555.003"
  ],
  "falsepositives": [
    "Legitimate browser activity or browser updates accessing their own profile databases (e.g., Cookies/Login Data/WebCache).",
    "Endpoint security, backup, EDR, or forensic tools scanning browser profile directories and related database/JSON files.",
    "Administrative troubleshooting or migration tools that read browser profile data."
  ],
  "mitre_techniques_inferred": []
}
```

---

## Rule 1007 (standalone)

```json
{
  "title": "Sysmon Remote Thread Creation from Uncommon Source Image (with Known Benign Exclusions)",
  "description": "Detects Sysmon Event ID 8 (CreateRemoteThread) where the source process image is an uncommon/rare initiator (living-off-the-land binaries and common apps), excluding several known benign source/target image combinations (e.g., Defrag/makecab -> conhost, provtool -> svchost, userinit -> explorer, WINWORD -> Program Files targets, SysWOW64 explorer -> VMware Tools). This can indicate process injection (T1055).",
  "status": "stable",
  "level": "high",
  "logsource": {
    "category": "process_creation",
    "product": "windows",
    "service": "sysmon"
  },
  "detection": {
    "selections": [
      {
        "name": "selection_remote_thread",
        "field_values": [
          {
            "field": "EventID",
            "modifier": null,
            "values": [
              "8"
            ]
          },
          {
            "field": "SourceImage",
            "modifier": "contains",
            "values": [
              "\\bash.exe",
              "\\cscript.exe",
              "\\cvtres.exe",
              "\\defrag.exe",
              "\\dialer.exe",
              "\\dnx.exe",
              "\\esentutl.exe",
              "\\excel.exe",
              "\\expand.exe",
              "\\find.exe",
              "\\findstr.exe",
              "\\forfiles.exe",
              "\\gpupdate.exe",
              "\\hh.exe",
              "\\installutil.exe",
              "\\lync.exe",
              "\\makecab.exe",
              "\\mDNSResponder.exe",
              "\\monitoringhost.exe",
              "\\msbuild.exe",
              "\\mshta.exe",
              "\\mspaint.exe",
              "\\outlook.exe",
              "\\ping.exe",
              "\\provtool.exe",
              "\\python.exe",
              "\\regsvr32.exe",
              "\\robocopy.exe",
              "\\runonce.exe",
              "\\sapcimc.exe",
              "\\smartscreen.exe",
              "\\spoolsv.exe",
              "\\tstheme.exe",
              "\\userinit.exe",
              "\\vssadmin.exe",
              "\\vssvc.exe",
              "\\w3wp.exe",
              "\\winscp.exe",
              "\\winword.exe",
              "\\wmic.exe",
              "\\wscript.exe"
            ]
          }
        ]
      },
      {
        "name": "filter_defrag_makecab_to_conhost",
        "field_values": [
          {
            "field": "SourceImage",
            "modifier": "contains",
            "values": [
              "C:\\Windows\\System32\\Defrag.exe",
              "C:\\Windows\\System32\\makecab.exe"
            ]
          },
          {
            "field": "TargetImage",
            "modifier": "contains",
            "values": [
              "C:\\Windows\\System32\\conhost.exe"
            ]
          }
        ]
      },
      {
        "name": "filter_provtool_to_svchost",
        "field_values": [
          {
            "field": "SourceImage",
            "modifier": "contains",
            "values": [
              "C:\\Windows\\System32\\provtool.exe"
            ]
          },
          {
            "field": "TargetImage",
            "modifier": "contains",
            "values": [
              "C:\\Windows\\System32\\svchost.exe"
            ]
          }
        ]
      },
      {
        "name": "filter_userinit_to_explorer",
        "field_values": [
          {
            "field": "SourceImage",
            "modifier": "contains",
            "values": [
              "C:\\Windows\\System32\\userinit.exe"
            ]
          },
          {
            "field": "TargetImage",
            "modifier": "contains",
            "values": [
              "C:\\Windows\\explorer.exe"
            ]
          }
        ]
      },
      {
        "name": "filter_winword_to_program_files_targets",
        "field_values": [
          {
            "field": "SourceImage",
            "modifier": "contains",
            "values": [
              "\\WINWORD.EXE"
            ]
          },
          {
            "field": "TargetImage",
            "modifier": "contains",
            "values": [
              "C:\\Program Files (x86)\\",
              "C:\\Program Files\\"
            ]
          }
        ]
      },
      {
        "name": "filter_syswow64_explorer_to_vmware_tools",
        "field_values": [
          {
            "field": "SourceImage",
            "modifier": "contains",
            "values": [
              "\\SysWOW64\\explorer.exe"
            ]
          },
          {
            "field": "TargetImage",
            "modifier": "contains",
            "values": [
              "C:\\Program Files (x86)\\VMware\\VMware Tools\\vmtoolsd.exe",
              "C:\\Program Files\\VMware\\VMware Tools\\vmtoolsd.exe"
            ]
          }
        ]
      }
    ],
    "condition": "selection_remote_thread and not (filter_defrag_makecab_to_conhost or filter_provtool_to_svchost or filter_userinit_to_explorer or filter_winword_to_program_files_targets or filter_syswow64_explorer_to_vmware_tools)"
  },
  "tags": [
    "attack.privilege-escalation",
    "attack.t1055"
  ],
  "falsepositives": [
    "Legitimate software using CreateRemoteThread for automation, accessibility, endpoint management, or application add-ins (e.g., Office integrations) not covered by the current exclusions.",
    "VMware Tools and other virtualization/management agents performing benign remote thread creation outside the explicitly excluded paths.",
    "Administrative scripting or maintenance activity invoking listed binaries (e.g., wscript/cscript/msbuild/regsvr32) that legitimately inject into other processes."
  ],
  "mitre_techniques_inferred": []
}
```

---
