#!/usr/bin/python
# -*- encoding: utf-8; py-indent-offset: 4 -*-
# +------------------------------------------------------------------+
# |             ____ _               _        __  __ _  __           |
# |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
# |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
# |           | |___| | | |  __/ (__|   <    | |  | | . \            |
# |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
# |                                                                  |
# | Copyright Mathias Kettner 2014             mk@mathias-kettner.de |
# +------------------------------------------------------------------+
#
# This file is part of Check_MK.
# The official homepage is at http://mathias-kettner.de/check_mk.
#
# check_mk is free software;  you can redistribute it and/or modify it
# under the  terms of the  GNU General Public License  as published by
# the Free Software Foundation in version 2.  check_mk is  distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
# out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
# PARTICULAR PURPOSE. See the  GNU General Public License for more de-
# tails. You should have  received  a copy of the  GNU  General Public
# License along with GNU Make; see the file  COPYING.  If  not,  write
# to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
# Boston, MA 02110-1301 USA.

from cmk.utils.defines import short_service_state_name

import cmk.gui.config as config
import cmk.gui.sites as sites
import cmk.gui.mkeventd as mkeventd
from cmk.gui.valuespec import MonitoringState
from cmk.gui.i18n import _
from cmk.gui.globals import html

from cmk.gui.plugins.views import (
    get_permitted_views,
    command_registry,
    Command,
    data_source_registry,
    DataSource,
    RowTableLivestatus,
    painter_registry,
    Painter,
    multisite_builtin_views,
    paint_age,
    paint_nagiosflag,
    row_id,
    declare_1to1_sorter,
    cmp_simple_number,
    cmp_simple_string,
    cmp_num_split,
)

from cmk.gui.permissions import (
    permission_registry,
    Permission,
)

#   .--Datasources---------------------------------------------------------.
#   |       ____        _                                                  |
#   |      |  _ \  __ _| |_ __ _ ___  ___  _   _ _ __ ___ ___  ___         |
#   |      | | | |/ _` | __/ _` / __|/ _ \| | | | '__/ __/ _ \/ __|        |
#   |      | |_| | (_| | || (_| \__ \ (_) | |_| | | | (_|  __/\__ \        |
#   |      |____/ \__,_|\__\__,_|___/\___/ \__,_|_|  \___\___||___/        |
#   |                                                                      |
#   '----------------------------------------------------------------------'


class RowTableEC(RowTableLivestatus):
    def query(self, view, columns, headers, only_sites, limit, all_active_filters):
        for c in ["event_contact_groups", "host_contact_groups", "event_host"]:
            if c not in columns:
                columns.append(c)

        rows = super(RowTableEC, self).query(view, columns, headers, only_sites, limit,
                                             all_active_filters)

        if not rows:
            return rows

        _ec_filter_host_information_of_not_permitted_hosts(rows)

        if not config.user.may("mkeventd.seeall") and not config.user.may("mkeventd.seeunrelated"):
            # user is not allowed to see all events returned by the core
            rows = [r for r in rows if r["event_contact_groups"] != [] or r["host_name"] != ""]

        # Now we don't need to distinguish anymore between unrelated and related events. We
        # need the host_name field for rendering the views. Try our best and use the
        # event_host value as host_name.
        for row in rows:
            if not row.get("host_name"):
                row["host_name"] = row["event_host"]
                row["event_is_unrelated"] = True

        return rows


# Handle the case where a user is allowed to see all events (-> events for hosts he
# is not permitted for). In this case the user should be allowed to see the event
# information, but not the host related information.
#
# To realize this, whe filter all data from the host_* columns from the response.
# See Gitbug #2462 for some more information.
#
# This should be handled in the core, but the core does not know anything about
# the "mkeventd.seeall" permissions. So it is simply not possible to do this on
# core level at the moment.
def _ec_filter_host_information_of_not_permitted_hosts(rows):
    if config.user.may("mkeventd.seeall"):
        return  # Don't remove anything. The user may see everything

    user_groups = set(config.user.contact_groups())

    def is_contact(row):
        return bool(user_groups.intersection(row["host_contact_groups"]))

    if rows:
        remove_keys = [c for c in rows[0].keys() if c.startswith("host_")]
    else:
        remove_keys = []

    for row in rows:
        if row["host_name"] == "":
            continue  # This is an "unrelated host", don't treat it here

        if is_contact(row):
            continue  # The user may see these host information

        # Now remove the host information. This can sadly not apply the cores
        # default values for the different columns. We try our best to clean up
        for key in remove_keys:
            if isinstance(row[key], list):
                row[key] = []
            elif isinstance(row[key], int):
                row[key] = 0
            elif isinstance(row[key], float):
                row[key] = 0.0
            elif isinstance(row[key], str):
                row[key] = ""
            elif isinstance(row[key], unicode):
                row[key] = u""


@permission_registry.register
class PermissionECSeeAll(Permission):
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "seeall"

    @property
    def title(self):
        return _("See all events")

    @property
    def description(self):
        return _("If a user lacks this permission then he/she can see only those events that "
                 "originate from a host that he/she is a contact for.")

    @property
    def defaults(self):
        return config.builtin_role_ids


@permission_registry.register
class PermissionECSeeUnrelated(Permission):
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "seeunrelated"

    @property
    def title(self):
        return _("See events not related to a known host")

    @property
    def description(self):
        return _(
            "If that user does not have the permission <i>See all events</i> then this permission "
            "controls wether he/she can see events that are not related to a host in the monitoring "
            "and that do not have been assigned specific contact groups to via the event rule.")

    @property
    def defaults(self):
        return config.builtin_role_ids


@permission_registry.register
class PermissionECSeeInTacticalOverview(Permission):
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "see_in_tactical_overview"

    @property
    def title(self):
        return _("See events in tactical overview snapin")

    @property
    def description(self):
        return _("Whether or not the user is permitted to see the number of open events in the "
                 "tactical overview snapin.")

    @property
    def defaults(self):
        return config.builtin_role_ids


@data_source_registry.register
class DataSourceECEvents(DataSource):
    @property
    def ident(self):
        return "mkeventd_events"

    @property
    def title(self):
        return _("Event Console: Current Events")

    @property
    def table(self):
        return RowTableEC("eventconsoleevents")

    @property
    def infos(self):
        return ["event", "host"]

    @property
    def keys(self):
        return []

    @property
    def id_keys(self):
        return ['site', 'host_name', 'event_id']

    @property
    def auth_domain(self):
        return "ec"

    @property
    def time_filters(self):
        return ["event_first"]


@data_source_registry.register
class DataSourceECEventHistory(DataSource):
    @property
    def ident(self):
        return "mkeventd_history"

    @property
    def title(self):
        return _("Event Console: Event History")

    @property
    def table(self):
        return RowTableEC("eventconsolehistory")

    @property
    def infos(self):
        return ["history", "event", "host"]

    @property
    def keys(self):
        return []

    @property
    def id_keys(self):
        return ['site', 'host_name', 'event_id', 'history_line']

    @property
    def auth_domain(self):
        return "ec"

    @property
    def time_filters(self):
        return ["history_time"]


#.
#   .--Painters------------------------------------------------------------.
#   |                 ____       _       _                                 |
#   |                |  _ \ __ _(_)_ __ | |_ ___ _ __ ___                  |
#   |                | |_) / _` | | '_ \| __/ _ \ '__/ __|                 |
#   |                |  __/ (_| | | | | | ||  __/ |  \__ \                 |
#   |                |_|   \__,_|_|_| |_|\__\___|_|  |___/                 |
#   |                                                                      |
#   '----------------------------------------------------------------------'


@painter_registry.register
class PainterEventId(Painter):
    @property
    def ident(self):
        return "event_id"

    @property
    def title(self):
        return _("ID of the event")

    @property
    def short_title(self):
        return _("ID")

    @property
    def columns(self):
        return ['event_id']

    def render(self, row, cell):
        return ("number", str(row["event_id"]))


@painter_registry.register
class PainterEventCount(Painter):
    @property
    def ident(self):
        return "event_count"

    @property
    def title(self):
        return _("Count (number of recent occurrances)")

    @property
    def short_title(self):
        return _("Cnt.")

    @property
    def columns(self):
        return ['event_count']

    def render(self, row, cell):
        return ("number", str(row["event_count"]))


@painter_registry.register
class PainterEventText(Painter):
    @property
    def ident(self):
        return "event_text"

    @property
    def title(self):
        return _("Text/Message of the event")

    @property
    def short_title(self):
        return _("Message")

    @property
    def columns(self):
        return ['event_text']

    def render(self, row, cell):
        return ("", html.attrencode(row["event_text"]).replace("\x01", "<br>"))


@painter_registry.register
class PainterEventMatchGroups(Painter):
    @property
    def ident(self):
        return "event_match_groups"

    @property
    def title(self):
        return _("Match Groups")

    @property
    def short_title(self):
        return _("Match")

    @property
    def columns(self):
        return ['event_match_groups']

    def render(self, row, cell):
        groups = row["event_match_groups"]
        if groups:
            code = ""
            for text in groups:
                code += '<span>%s</span>' % text
            return "matchgroups", code
        return "", ""


@painter_registry.register
class PainterEventFirst(Painter):
    @property
    def ident(self):
        return "event_first"

    @property
    def title(self):
        return _("Time of first occurrence of this serial")

    @property
    def short_title(self):
        return _("First")

    @property
    def columns(self):
        return ['event_first']

    @property
    def painter_options(self):
        return ['ts_format', 'ts_date']

    def render(self, row, cell):
        return paint_age(row["event_first"], True, True)


@painter_registry.register
class PainterEventLast(Painter):
    @property
    def ident(self):
        return "event_last"

    @property
    def title(self):
        return _("Time of last occurrance")

    @property
    def short_title(self):
        return _("Last")

    @property
    def columns(self):
        return ['event_last']

    @property
    def painter_options(self):
        return ['ts_format', 'ts_date']

    def render(self, row, cell):
        return paint_age(row["event_last"], True, True)


@painter_registry.register
class PainterEventComment(Painter):
    @property
    def ident(self):
        return "event_comment"

    @property
    def title(self):
        return _("Comment to the event")

    @property
    def short_title(self):
        return _("Comment")

    @property
    def columns(self):
        return ['event_comment']

    def render(self, row, cell):
        return ("", row["event_comment"])


@painter_registry.register
class PainterEventSl(Painter):
    @property
    def ident(self):
        return "event_sl"

    @property
    def title(self):
        return _("Service-Level")

    @property
    def short_title(self):
        return _("Level")

    @property
    def columns(self):
        return ['event_sl']

    def render(self, row, cell):
        sl_txt = dict(config.mkeventd_service_levels).get(row["event_sl"], str(row["event_sl"]))
        return "", sl_txt


@painter_registry.register
class PainterEventHost(Painter):
    @property
    def ident(self):
        return "event_host"

    @property
    def title(self):
        return _("Hostname")

    @property
    def short_title(self):
        return _("Host")

    @property
    def columns(self):
        return ['event_host', 'host_name']

    def render(self, row, cell):
        if row["host_name"]:
            return "", row["host_name"]
        return "", row["event_host"]


@painter_registry.register
class PainterEventIpaddress(Painter):
    @property
    def ident(self):
        return "event_ipaddress"

    @property
    def title(self):
        return _("Original IP-Address")

    @property
    def short_title(self):
        return _("Orig. IP")

    @property
    def columns(self):
        return ['event_ipaddress']

    def render(self, row, cell):
        return ("", row["event_ipaddress"])


@painter_registry.register
class PainterEventHostInDowntime(Painter):
    @property
    def ident(self):
        return "event_host_in_downtime"

    @property
    def title(self):
        return _("Host in downtime during event creation")

    @property
    def short_title(self):
        return _("Dt.")

    @property
    def columns(self):
        return ['event_host_in_downtime']

    def render(self, row, cell):
        return paint_nagiosflag(row, "event_host_in_downtime", True)


@painter_registry.register
class PainterEventOwner(Painter):
    @property
    def ident(self):
        return "event_owner"

    @property
    def title(self):
        return _("Owner of event")

    @property
    def short_title(self):
        return _("owner")

    @property
    def columns(self):
        return ['event_owner']

    def render(self, row, cell):
        return ("", row["event_owner"])


@painter_registry.register
class PainterEventContact(Painter):
    @property
    def ident(self):
        return "event_contact"

    @property
    def title(self):
        return _("Contact Person")

    @property
    def short_title(self):
        return _("Contact")

    @property
    def columns(self):
        return ['event_contact']

    def render(self, row, cell):
        return ("", row["event_contact"])


@painter_registry.register
class PainterEventApplication(Painter):
    @property
    def ident(self):
        return "event_application"

    @property
    def title(self):
        return _("Application / Syslog-Tag")

    @property
    def short_title(self):
        return _("Application")

    @property
    def columns(self):
        return ['event_application']

    def render(self, row, cell):
        return ("", row["event_application"])


@painter_registry.register
class PainterEventPid(Painter):
    @property
    def ident(self):
        return "event_pid"

    @property
    def title(self):
        return _("Process ID")

    @property
    def short_title(self):
        return _("PID")

    @property
    def columns(self):
        return ['event_pid']

    def render(self, row, cell):
        return ("", "%s" % row["event_pid"])


@painter_registry.register
class PainterEventPriority(Painter):
    @property
    def ident(self):
        return "event_priority"

    @property
    def title(self):
        return _("Syslog-Priority")

    @property
    def short_title(self):
        return _("Prio")

    @property
    def columns(self):
        return ['event_priority']

    def render(self, row, cell):
        return ("", dict(mkeventd.syslog_priorities)[row["event_priority"]])


@painter_registry.register
class PainterEventFacility(Painter):
    @property
    def ident(self):
        return "event_facility"

    @property
    def title(self):
        return _("Syslog-Facility")

    @property
    def short_title(self):
        return _("Facility")

    @property
    def columns(self):
        return ['event_facility']

    def render(self, row, cell):
        return ("", dict(mkeventd.syslog_facilities)[row["event_facility"]])


@painter_registry.register
class PainterEventRuleId(Painter):
    @property
    def ident(self):
        return "event_rule_id"

    @property
    def title(self):
        return _("Rule-ID")

    @property
    def short_title(self):
        return _("Rule")

    @property
    def columns(self):
        return ['event_rule_id']

    def render(self, row, cell):
        rule_id = row["event_rule_id"]
        if config.user.may("mkeventd.edit"):
            urlvars = html.urlencode_vars([("mode", "mkeventd_edit_rule"), ("rule_id", rule_id)])
            return "", html.render_a(rule_id, "wato.py?%s" % urlvars)
        return "", rule_id


@painter_registry.register
class PainterEventState(Painter):
    @property
    def ident(self):
        return "event_state"

    @property
    def title(self):
        return _("State (severity) of event")

    @property
    def short_title(self):
        return _("State")

    @property
    def columns(self):
        return ['event_state']

    def render(self, row, cell):
        state = row["event_state"]
        name = short_service_state_name(state, "")
        return "state svcstate state%s" % state, name


@painter_registry.register
class PainterEventPhase(Painter):
    @property
    def ident(self):
        return "event_phase"

    @property
    def title(self):
        return _("Phase of event (open, counting, etc.)")

    @property
    def short_title(self):
        return _("Phase")

    @property
    def columns(self):
        return ['event_phase']

    def render(self, row, cell):
        return ("", mkeventd.phase_names.get(row["event_phase"], ''))


def paint_event_icons(row, history=False):
    htmlcode = render_event_phase_icons(row)

    if not history:
        htmlcode += render_delete_event_icons(row)

    if row["event_host_in_downtime"]:
        htmlcode += html.render_icon("downtime", _("Host in downtime during event creation"))

    if htmlcode:
        return "icons", htmlcode
    return "", ""


def render_event_phase_icons(row):
    phase = row["event_phase"]

    if phase == "ack":
        title = _("This event has been acknowledged.")
    elif phase == "counting":
        title = _("This event has not reached the target count yet.")
    elif phase == "delayed":
        title = _("The action of this event is still delayed in the hope of a cancelling event.")
    else:
        return ''

    return html.render_icon(phase, title=title)


def render_delete_event_icons(row):
    if config.user.may("mkeventd.delete"):
        urlvars = []

        # Found no cleaner way to get the view. Sorry.
        # TODO: This needs to be cleaned up with the new view implementation.
        if html.request.has_var("name") and html.request.has_var("id"):
            ident = int(html.request.var("id"))

            import cmk.gui.dashboard as dashboard
            dashboard.load_dashboards()
            view = dashboard.get_dashlet(html.request.var("name"), ident)

            # These actions are not performed within the dashlet. Assume the title url still
            # links to the source view where the action can be performed.
            title_url = view.get("title_url")
            if title_url:
                from urlparse import urlparse, parse_qsl
                url = urlparse(title_url)
                filename = url.path
                urlvars += parse_qsl(url.query)
        else:
            # Regular view
            view = get_permitted_views()[(html.request.var("view_name"))]
            filename = None

        urlvars += [
            ("filled_in", "actions"),
            ("actions", "yes"),
            ("_do_actions", "yes"),
            ("_row_id", row_id(view, row)),
            ("_delete_event", _("Archive Event")),
            ("_show_result", "0"),
        ]
        url = html.makeactionuri(urlvars,
                                 filename=filename,
                                 delvars=["selection", "show_checkboxes"])
        return html.render_icon_button(url, _("Archive this event"), "archive_event")
    else:
        return ''


@painter_registry.register
class PainterEventIcons(Painter):
    @property
    def ident(self):
        return "event_icons"

    @property
    def title(self):
        return _("Event Icons")

    @property
    def short_title(self):
        return _("Icons")

    @property
    def columns(self):
        return ['event_phase', 'event_host_in_downtime']

    @property
    def printable(self):
        return False

    def render(self, row, cell):
        return paint_event_icons(row)


@painter_registry.register
class PainterEventHistoryIcons(Painter):
    @property
    def ident(self):
        return "event_history_icons"

    @property
    def title(self):
        return _("Event Icons")

    @property
    def short_title(self):
        return _("Icons")

    @property
    def columns(self):
        return ['event_phase', 'event_host_in_downtime']

    @property
    def printable(self):
        return False

    def render(self, row, cell):
        return paint_event_icons(row, history=True)


@painter_registry.register
class PainterEventContactGroups(Painter):
    @property
    def ident(self):
        return "event_contact_groups"

    @property
    def title(self):
        return _("Contact groups defined in rule")

    @property
    def short_title(self):
        return _("Rule contact groups")

    @property
    def columns(self):
        return ['event_contact_groups']

    def render(self, row, cell):
        cgs = row.get("event_contact_groups")
        if cgs is None:
            return "", ""
        elif cgs:
            return "", ", ".join(cgs)
        return "", "<i>" + _("none") + "</i>"


@painter_registry.register
class PainterEventEffectiveContactGroups(Painter):
    @property
    def ident(self):
        return "event_effective_contact_groups"

    @property
    def title(self):
        return _("Contact groups effective (Host or rule contact groups)")

    @property
    def short_title(self):
        return _("Contact groups")

    @property
    def columns(self):
        return [
            'event_contact_groups',
            'event_contact_groups_precedence',
            'host_contact_groups',
        ]

    def render(self, row, cell):
        if row["event_contact_groups_precedence"] == "host":
            cgs = row["host_contact_groups"]
        else:
            cgs = row["event_contact_groups"]

        if cgs is None:
            return "", ""
        elif cgs:
            return "", ", ".join(sorted(cgs))
        return "", "<i>" + _("none") + "</i>"


# Event History


@painter_registry.register
class PainterHistoryLine(Painter):
    @property
    def ident(self):
        return "history_line"

    @property
    def title(self):
        return _("Line number in log file")

    @property
    def short_title(self):
        return _("Line")

    @property
    def columns(self):
        return ['history_line']

    def render(self, row, cell):
        return ("number", "%s" % row["history_line"])


@painter_registry.register
class PainterHistoryTime(Painter):
    @property
    def ident(self):
        return "history_time"

    @property
    def title(self):
        return _("Time of entry in logfile")

    @property
    def short_title(self):
        return _("Time")

    @property
    def columns(self):
        return ['history_time']

    @property
    def painter_options(self):
        return ['ts_format', 'ts_date']

    def render(self, row, cell):
        return paint_age(row["history_time"], True, True)


@painter_registry.register
class PainterHistoryWhat(Painter):
    @property
    def ident(self):
        return "history_what"

    @property
    def title(self):
        return _("Type of event action")

    @property
    def short_title(self):
        return _("Action")

    @property
    def columns(self):
        return ['history_what']

    def render(self, row, cell):
        what = row["history_what"]
        return "", '<span title="%s">%s</span>' % (mkeventd.action_whats[what], what)


@painter_registry.register
class PainterHistoryWhatExplained(Painter):
    @property
    def ident(self):
        return "history_what_explained"

    @property
    def title(self):
        return _("Explanation for event action")

    @property
    def columns(self):
        return ['history_what']

    def render(self, row, cell):
        return ("", mkeventd.action_whats[row["history_what"]])


@painter_registry.register
class PainterHistoryWho(Painter):
    @property
    def ident(self):
        return "history_who"

    @property
    def title(self):
        return _("User who performed action")

    @property
    def short_title(self):
        return _("Who")

    @property
    def columns(self):
        return ['history_who']

    def render(self, row, cell):
        return ("", row["history_who"])


@painter_registry.register
class PainterHistoryAddinfo(Painter):
    @property
    def ident(self):
        return "history_addinfo"

    @property
    def title(self):
        return _("Additional Information")

    @property
    def short_title(self):
        return _("Info")

    @property
    def columns(self):
        return ['history_addinfo']

    def render(self, row, cell):
        return ("", row["history_addinfo"])


#.
#   .--Commands------------------------------------------------------------.
#   |         ____                                          _              |
#   |        / ___|___  _ __ ___  _ __ ___   __ _ _ __   __| |___          |
#   |       | |   / _ \| '_ ` _ \| '_ ` _ \ / _` | '_ \ / _` / __|         |
#   |       | |__| (_) | | | | | | | | | | | (_| | | | | (_| \__ \         |
#   |        \____\___/|_| |_| |_|_| |_| |_|\__,_|_| |_|\__,_|___/         |
#   |                                                                      |
#   '----------------------------------------------------------------------'


@permission_registry.register
class PermissionECUpdateEvent(Permission):
    """Acknowledge and update comment and contact"""
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "update"

    @property
    def title(self):
        return _("Update an event")

    @property
    def description(self):
        return _("Needed for acknowledging and changing the comment and contact of an event")

    @property
    def defaults(self):
        return ["user", "admin"]


@permission_registry.register
class PermissionECUpdateComment(Permission):
    """Sub-Permissions for Changing Comment, Contact and Acknowledgement"""
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "update_comment"

    @property
    def title(self):
        return _("Update an event: change comment")

    @property
    def description(self):
        return _("Needed for changing a comment when updating an event")

    @property
    def defaults(self):
        return ["user", "admin"]


@permission_registry.register
class PermissionECUpdateContact(Permission):
    """Sub-Permissions for Changing Comment, Contact and Acknowledgement"""
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "update_contact"

    @property
    def title(self):
        return _("Update an event: change contact")

    @property
    def description(self):
        return _("Needed for changing a contact when updating an event")

    @property
    def defaults(self):
        return ["user", "admin"]


class ECCommand(Command):
    @property
    def tables(self):
        return ["event"]

    def executor(self, command, site):
        mkeventd.execute_command(command, site=site)


@command_registry.register
class CommandECUpdateEvent(ECCommand):
    @property
    def ident(self):
        return "ec_update_event"

    @property
    def title(self):
        return _("Update & Acknowledge")

    @property
    def permission(self):
        return PermissionECUpdateEvent

    def render(self, what):
        html.open_table(border=0, cellpadding=0, cellspacing=3)
        if config.user.may("mkeventd.update_comment"):
            html.open_tr()
            html.open_td()
            html.write(_("Change comment:"))
            html.close_td()
            html.open_td()
            html.text_input('_mkeventd_comment', size=50)
            html.close_td()
            html.close_tr()
        if config.user.may("mkeventd.update_contact"):
            html.open_tr()
            html.open_td()
            html.write(_("Change contact:"))
            html.close_td()
            html.open_td()
            html.text_input('_mkeventd_contact', size=50)
            html.close_td()
            html.close_tr()
        html.open_tr()
        html.td('')
        html.open_td()
        html.checkbox('_mkeventd_acknowledge', True, label=_("Set event to acknowledged"))
        html.close_td()
        html.close_tr()
        html.close_table()
        html.button('_mkeventd_update', _("Update"))

    def action(self, cmdtag, spec, row, row_index, num_rows):
        if html.request.var('_mkeventd_update'):
            if config.user.may("mkeventd.update_comment"):
                comment = html.get_unicode_input("_mkeventd_comment").strip().replace(";", ",")
            else:
                comment = ""
            if config.user.may("mkeventd.update_contact"):
                contact = html.get_unicode_input("_mkeventd_contact").strip().replace(":", ",")
            else:
                contact = ""
            ack = html.get_checkbox("_mkeventd_acknowledge")
            return "UPDATE;%s;%s;%s;%s;%s" % (row["event_id"], config.user.id, ack and 1 or
                                              0, comment, contact), _("update")


@permission_registry.register
class PermissionECChangeEventState(Permission):
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "changestate"

    @property
    def title(self):
        return _("Change event state")

    @property
    def description(self):
        return _("This permission allows to change the state classification of an event "
                 "(e.g. from CRIT to WARN).")

    @property
    def defaults(self):
        return ["user", "admin"]


@command_registry.register
class CommandECChangeState(ECCommand):
    @property
    def ident(self):
        return "ec_change_state"

    @property
    def title(self):
        return _("Change State")

    @property
    def permission(self):
        return PermissionECChangeEventState

    def render(self, what):
        html.button('_mkeventd_changestate', _("Change Event state to:"))
        html.nbsp()
        MonitoringState().render_input("_mkeventd_state", 2)

    def action(self, cmdtag, spec, row, row_index, num_rows):
        if html.request.var('_mkeventd_changestate'):
            state = MonitoringState().from_html_vars("_mkeventd_state")
            return "CHANGESTATE;%s;%s;%s" % (row["event_id"], config.user.id,
                                             state), _("change the state")


@permission_registry.register
class PermissionECCustomActions(Permission):
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "actions"

    @property
    def title(self):
        return _("Perform custom action")

    @property
    def description(self):
        return _("This permission is needed for performing the configured actions "
                 "(execution of scripts and sending emails).")

    @property
    def defaults(self):
        return ["user", "admin"]


@command_registry.register
class CommandECCustomAction(ECCommand):
    @property
    def ident(self):
        return "ec_custom_actions"

    @property
    def title(self):
        return _("Custom Action")

    @property
    def permission(self):
        return PermissionECCustomActions

    def render(self, what):
        for action_id, title in mkeventd.action_choices(omit_hidden=True):
            html.button("_action_" + action_id, title)
            html.br()

    def action(self, cmdtag, spec, row, row_index, num_rows):
        for action_id, title in mkeventd.action_choices(omit_hidden=True):
            if html.request.var("_action_" + action_id):
                return "ACTION;%s;%s;%s" % (row["event_id"], config.user.id, action_id), (
                    _("execute the action \"%s\"") % title)


@permission_registry.register
class PermissionECArchiveEvent(Permission):
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "delete"

    @property
    def title(self):
        return _("Archive an event")

    @property
    def description(self):
        return _("Finally archive an event without any further action")

    @property
    def defaults(self):
        return ["user", "admin"]


@command_registry.register
class CommandECArchiveEvent(ECCommand):
    @property
    def ident(self):
        return "ec_archive_event"

    @property
    def title(self):
        return _("Archive Event")

    @property
    def permission(self):
        return PermissionECArchiveEvent

    def render(self, what):
        html.button("_delete_event", _("Archive Event"))

    def action(self, cmdtag, spec, row, row_index, num_rows):
        if html.request.var("_delete_event"):
            command = "DELETE;%s;%s" % (row["event_id"], config.user.id)
            title = _("<b>archive</b>")
            return command, title


@permission_registry.register
class PermissionECArchiveEventsOfHost(Permission):
    @property
    def section(self):
        return mkeventd.PermissionSectionEventConsole

    @property
    def permission_name(self):
        return "archive_events_of_hosts"

    @property
    def title(self):
        return _("Archive events of hosts")

    @property
    def description(self):
        return _("Archive all open events of all hosts shown in host views")

    @property
    def defaults(self):
        return ["user", "admin"]


@command_registry.register
class CommandECArchiveEventsOfHost(ECCommand):
    @property
    def ident(self):
        return "ec_archive_events_of_host"

    @property
    def title(self):
        return _("Archive events of hosts")

    @property
    def permission(self):
        return PermissionECArchiveEventsOfHost

    @property
    def tables(self):
        return ["host", "service"]

    def render(self, what):
        html.button("_archive_events_of_hosts", _('Archive events'))

    def action(self, cmdtag, spec, row, row_index, num_rows):
        if html.request.var("_archive_events_of_hosts"):
            if cmdtag == "HOST":
                tag = "host"
            elif cmdtag == "SVC":
                tag = "service"
            else:
                tag = None

            commands = []
            if tag and row.get('%s_check_command' % tag, "").startswith('check_mk_active-mkevents'):
                data = sites.live().query("GET eventconsoleevents\n" + "Columns: event_id\n" +
                                          "Filter: host_name = %s" % row['host_name'])
                commands = ["DELETE;%s;%s" % (entry[0], config.user.id) for entry in data]
            return commands, "<b>archive all events of all hosts</b> of"


#.
#   .--Sorters-------------------------------------------------------------.
#   |                  ____             _                                  |
#   |                 / ___|  ___  _ __| |_ ___ _ __ ___                   |
#   |                 \___ \ / _ \| '__| __/ _ \ '__/ __|                  |
#   |                  ___) | (_) | |  | ||  __/ |  \__ \                  |
#   |                 |____/ \___/|_|   \__\___|_|  |___/                  |
#   |                                                                      |
#   '----------------------------------------------------------------------'


def cmp_simple_state(column, ra, rb):
    a = ra.get(column, -1)
    b = rb.get(column, -1)
    if a == 3:
        a = 1.5
    if b == 3:
        b = 1.5
    return cmp(a, b)


declare_1to1_sorter("event_id", cmp_simple_number)
declare_1to1_sorter("event_count", cmp_simple_number)
declare_1to1_sorter("event_text", cmp_simple_string)
declare_1to1_sorter("event_first", cmp_simple_number)
declare_1to1_sorter("event_last", cmp_simple_number)
declare_1to1_sorter("event_comment", cmp_simple_string)
declare_1to1_sorter("event_sl", cmp_simple_number)
declare_1to1_sorter("event_host", cmp_num_split)
declare_1to1_sorter("event_ipaddress", cmp_num_split)
declare_1to1_sorter("event_contact", cmp_simple_string)
declare_1to1_sorter("event_application", cmp_simple_string)
declare_1to1_sorter("event_pid", cmp_simple_number)
declare_1to1_sorter("event_priority", cmp_simple_number)
declare_1to1_sorter("event_facility", cmp_simple_number)  # maybe convert to text
declare_1to1_sorter("event_rule_id", cmp_simple_string)
declare_1to1_sorter("event_state", cmp_simple_state)
declare_1to1_sorter("event_phase", cmp_simple_string)
declare_1to1_sorter("event_owner", cmp_simple_string)

declare_1to1_sorter("history_line", cmp_simple_number)
declare_1to1_sorter("history_time", cmp_simple_number)
declare_1to1_sorter("history_what", cmp_simple_string)
declare_1to1_sorter("history_who", cmp_simple_string)
declare_1to1_sorter("history_addinfo", cmp_simple_string)

#.
#   .--Views---------------------------------------------------------------.
#   |                    __     ___                                        |
#   |                    \ \   / (_) _____      _____                      |
#   |                     \ \ / /| |/ _ \ \ /\ / / __|                     |
#   |                      \ V / | |  __/\ V  V /\__ \                     |
#   |                       \_/  |_|\___| \_/\_/ |___/                     |
#   |                                                                      |
#   '----------------------------------------------------------------------'


def mkeventd_view(d):
    x = {
        'topic': _('Event Console'),
        'browser_reload': 60,
        'column_headers': 'pergroup',
        'icon': 'mkeventd',
        'mobile': False,
        'hidden': False,
        'mustsearch': False,
        'group_painters': [],
        'num_columns': 1,
        'hidebutton': False,
        'play_sounds': False,
        'public': True,
        'sorters': [],
        'user_sortable': 'on',
        'show_filters': [],
        'hard_filters': [],
        'hide_filters': [],
        'hard_filtervars': [],
    }
    x.update(d)
    return x


# Table of all open events
multisite_builtin_views['ec_events'] = mkeventd_view({
    'title': _('Events'),
    'description': _('Table of all currently open events (handled and unhandled)'),
    'datasource': 'mkeventd_events',
    'layout': 'table',
    'painters': [
        ('event_id', 'ec_event', None),
        ('event_icons', None, None),
        ('event_state', None, None),
        ('event_sl', None, None),
        ('event_host', 'ec_events_of_host', None),
        ('event_rule_id', None, None),
        ('event_application', None, None),
        ('event_text', None, None),
        ('event_last', None, None),
        ('event_count', None, None),
    ],
    'show_filters': [
        'event_id',
        'event_rule_id',
        'event_text',
        'event_application',
        'event_contact',
        'event_comment',
        'event_host_regex',
        'event_ipaddress',
        'event_count',
        'event_phase',
        'event_state',
        'event_first',
        'event_last',
        'event_priority',
        'event_facility',
        'event_sl',
        'event_sl_max',
        'event_host_in_downtime',
        'hostregex',
        'siteopt',
    ],
    'hard_filtervars': [
        ('event_phase_open', "on"),
        ('event_phase_ack', "on"),
        ('event_phase_counting', ""),
        ('event_phase_delayed', ""),
    ],
    'sorters': [('event_last', False)],
})

multisite_builtin_views['ec_events_of_monhost'] = mkeventd_view({
    'title': _('Events of Monitored Host'),
    'description': _('Currently open events of a host that is monitored'),
    'datasource': 'mkeventd_events',
    'layout': 'table',
    'hidden': True,
    'painters': [
        ('event_id', 'ec_event', None),
        ('event_icons', None, None),
        ('event_state', None, None),
        ('event_sl', None, None),
        ('event_rule_id', None, None),
        ('event_application', None, None),
        ('event_text', None, None),
        ('event_last', None, None),
        ('event_count', None, None),
    ],
    'show_filters': [
        'event_id',
        'event_rule_id',
        'event_text',
        'event_application',
        'event_contact',
        'event_comment',
        'event_count',
        'event_phase',
        'event_state',
        'event_first',
        'event_last',
        'event_priority',
        'event_facility',
        'event_sl',
        'event_sl_max',
        'event_host_in_downtime',
    ],
    'hide_filters': [
        'siteopt',
        'host',
    ],
    'sorters': [('event_last', False)],
})
multisite_builtin_views['ec_events_of_host'] = mkeventd_view({
    'title': _('Events of Host'),
    'description': _('Currently open events of one specific host'),
    'datasource': 'mkeventd_events',
    'layout': 'table',
    'hidden': True,
    'painters': [
        ('event_id', 'ec_event', None),
        ('event_icons', None, None),
        ('event_state', None, None),
        ('event_sl', None, None),
        ('event_rule_id', None, None),
        ('event_application', None, None),
        ('event_text', None, None),
        ('event_last', None, None),
        ('event_count', None, None),
    ],
    'show_filters': [
        'event_id',
        'event_rule_id',
        'event_text',
        'event_application',
        'event_contact',
        'event_comment',
        'event_count',
        'event_phase',
        'event_state',
        'event_first',
        'event_last',
        'event_priority',
        'event_facility',
        'event_sl',
        'event_sl_max',
        'event_host_in_downtime',
    ],
    'hide_filters': [
        'siteopt',
        'event_host',
    ],
    'sorters': [('event_last', False)],
})

multisite_builtin_views['ec_event'] = mkeventd_view({
    'title': _('Event Details'),
    'description': _('Details about one event'),
    'linktitle': 'Event Details',
    'datasource': 'mkeventd_events',
    'layout': 'dataset',
    'hidden': True,
    'browser_reload': 0,
    'hide_filters': ['event_id',],
    'painters': [
        ('event_state', None, None),
        ('event_host', None, None),
        ('event_ipaddress', None, None),
        ('foobar', None, None),
        ('alias', 'hoststatus', None),
        ('host_contacts', None, None),
        ('host_icons', None, None),
        ('event_text', None, None),
        ('event_match_groups', None, None),
        ('event_comment', None, None),
        ('event_owner', None, None),
        ('event_first', None, None),
        ('event_last', None, None),
        ('event_id', None, None),
        ('event_icons', None, None),
        ('event_count', None, None),
        ('event_sl', None, None),
        ('event_contact', None, None),
        ('event_effective_contact_groups', None, None),
        ('event_application', None, None),
        ('event_pid', None, None),
        ('event_priority', None, None),
        ('event_facility', None, None),
        ('event_rule_id', None, None),
        ('event_phase', None, None),
        ('host_services', None, None),
    ],
})

multisite_builtin_views['ec_history_recent'] = mkeventd_view({
    'title': _('Recent Event History'),
    'description': _('Information about events and actions on events during the recent 24 hours.'),
    'datasource': 'mkeventd_history',
    'layout': 'table',
    'painters': [
        ('history_time', None, None),
        ('event_id', 'ec_historyentry', None),
        ('history_who', None, None),
        ('history_what', None, None),
        ('event_history_icons', None, None),
        ('event_state', None, None),
        ('event_phase', None, None),
        ('event_sl', None, None),
        ('event_host', 'ec_history_of_host', None),
        ('event_rule_id', None, None),
        ('event_application', None, None),
        ('event_text', None, None),
        ('event_last', None, None),
        ('event_count', None, None),
    ],
    'show_filters': [
        'event_id',
        'event_rule_id',
        'event_text',
        'event_application',
        'event_contact',
        'event_comment',
        'event_host_regex',
        'event_ipaddress',
        'event_count',
        'event_phase',
        'event_state',
        'event_first',
        'event_last',
        'event_priority',
        'event_facility',
        'event_sl',
        'event_sl_max',
        'event_host_in_downtime',
        'history_time',
        'history_who',
        'history_what',
        'host_state_type',
        'hostregex',
        'siteopt',
    ],
    'hard_filtervars': [
        ('history_time_from', '1'),
        ('history_time_from_range', '86400'),
    ],
    'sorters': [
        ('history_time', True),
        ('history_line', True),
    ],
})

multisite_builtin_views['ec_historyentry'] = mkeventd_view({
    'title': _('Event History Entry'),
    'description': _('Details about a historical event history entry'),
    'datasource': 'mkeventd_history',
    'layout': 'dataset',
    'hidden': True,
    'browser_reload': 0,
    'hide_filters': [
        'event_id',
        'history_line',
    ],
    'painters': [
        ('history_time', None, None),
        ('history_line', None, None),
        ('history_what', None, None),
        ('history_what_explained', None, None),
        ('history_who', None, None),
        ('history_addinfo', None, None),
        ('event_state', None, None),
        ('event_host', 'ec_history_of_host', None),
        ('event_ipaddress', None, None),
        ('event_text', None, None),
        ('event_match_groups', None, None),
        ('event_comment', None, None),
        ('event_owner', None, None),
        ('event_first', None, None),
        ('event_last', None, None),
        ('event_id', 'ec_history_of_event', None),
        ('event_history_icons', None, None),
        ('event_count', None, None),
        ('event_sl', None, None),
        ('event_contact', None, None),
        ('event_effective_contact_groups', None, None),
        ('event_application', None, None),
        ('event_pid', None, None),
        ('event_priority', None, None),
        ('event_facility', None, None),
        ('event_rule_id', None, None),
        ('event_phase', None, None),
    ],
})

multisite_builtin_views['ec_history_of_event'] = mkeventd_view({
    'title': _('History of Event'),
    'description': _('History entries of one specific event'),
    'datasource': 'mkeventd_history',
    'layout': 'table',
    'columns': 1,
    'hidden': True,
    'browser_reload': 0,
    'hide_filters': ['event_id',],
    'painters': [
        ('history_time', None, None),
        ('history_line', 'ec_historyentry', None),
        ('history_what', None, None),
        ('history_what_explained', None, None),
        ('history_who', None, None),
        ('event_state', None, None),
        ('event_host', None, None),
        ('event_application', None, None),
        ('event_text', None, None),
        ('event_sl', None, None),
        ('event_priority', None, None),
        ('event_facility', None, None),
        ('event_phase', None, None),
        ('event_count', None, None),
    ],
    'sorters': [
        ('history_time', True),
        ('history_line', True),
    ],
})

multisite_builtin_views['ec_history_of_host'] = mkeventd_view({
    'title': _('Event History of Host'),
    'description': _('History entries of one specific host'),
    'datasource': 'mkeventd_history',
    'layout': 'table',
    'columns': 1,
    'hidden': True,
    'browser_reload': 0,
    'hide_filters': ['event_host',],
    'show_filters': [
        'event_id',
        'event_rule_id',
        'event_text',
        'event_application',
        'event_contact',
        'event_comment',
        'event_count',
        'event_phase',
        'event_state',
        'event_first',
        'event_last',
        'event_priority',
        'event_facility',
        'event_sl',
        'event_sl_max',
        'event_host_in_downtime',
        'history_time',
        'history_who',
        'history_what',
    ],
    'painters': [
        ('history_time', None, None),
        ('event_id', 'ec_history_of_event', None),
        ('history_line', 'ec_historyentry', None),
        ('history_what', None, None),
        ('history_what_explained', None, None),
        ('history_who', None, None),
        ('event_state', None, None),
        ('event_host', None, None),
        ('event_ipaddress', None, None),
        ('event_application', None, None),
        ('event_text', None, None),
        ('event_sl', None, None),
        ('event_priority', None, None),
        ('event_facility', None, None),
        ('event_phase', None, None),
        ('event_count', None, None),
    ],
    'sorters': [
        ('history_time', True),
        ('history_line', True),
    ],
})

multisite_builtin_views['ec_event_mobile'] = {
    'browser_reload': 0,
    'column_headers': 'pergroup',
    'context': {},
    'datasource': 'mkeventd_events',
    'description': u'Details about one event\n',
    'group_painters': [],
    'hidden': True,
    'hidebutton': False,
    'icon': 'mkeventd',
    'layout': 'mobiledataset',
    'linktitle': u'Event Details',
    'mobile': True,
    'name': 'ec_event_mobile',
    'num_columns': 1,
    'painters': [
        ('event_state', None, None),
        ('event_host', None, None),
        ('event_ipaddress', None, None),
        ('host_address', 'hoststatus', None),
        ('host_contacts', None, None),
        ('host_icons', None, None),
        ('event_text', None, None),
        ('event_comment', None, None),
        ('event_owner', None, None),
        ('event_first', None, None),
        ('event_last', None, None),
        ('event_id', None, None),
        ('event_icons', None, None),
        ('event_count', None, None),
        ('event_sl', None, None),
        ('event_contact', None, None),
        ('event_effective_contact_groups', None, None),
        ('event_application', None, None),
        ('event_pid', None, None),
        ('event_priority', None, None),
        ('event_facility', None, None),
        ('event_rule_id', None, None),
        ('event_phase', None, None),
        ('host_services', None, None),
    ],
    'public': True,
    'single_infos': ['event'],
    'sorters': [],
    'title': u'Event Details',
    'topic': u'Event Console',
    'user_sortable': True
}

multisite_builtin_views['ec_events_mobile'] = {
    'browser_reload': 60,
    'column_headers': 'pergroup',
    'context': {
        'event_application': {
            'event_application': ''
        },
        'event_comment': {
            'event_comment': ''
        },
        'event_contact': {
            'event_contact': ''
        },
        'event_count': {
            'event_count_from': '',
            'event_count_to': ''
        },
        'event_facility': {
            'event_facility': ''
        },
        'event_first': {
            'event_first_from': '',
            'event_first_from_range': '3600',
            'event_first_until': '',
            'event_first_until_range': '3600'
        },
        'event_host_regex': {
            'event_host_regex': ''
        },
        'event_id': {
            'event_id': ''
        },
        'event_last': {
            'event_last_from': '',
            'event_last_from_range': '3600',
            'event_last_until': '',
            'event_last_until_range': '3600'
        },
        'event_phase': {
            'event_phase_ack': 'on',
            'event_phase_closed': 'on',
            'event_phase_counting': '',
            'event_phase_delayed': '',
            'event_phase_open': 'on'
        },
        'event_priority': {
            'event_priority_0': 'on',
            'event_priority_1': 'on',
            'event_priority_2': 'on',
            'event_priority_3': 'on',
            'event_priority_4': 'on',
            'event_priority_5': 'on',
            'event_priority_6': 'on',
            'event_priority_7': 'on'
        },
        'event_rule_id': {
            'event_rule_id': ''
        },
        'event_sl': {
            'event_sl': ''
        },
        'event_sl_max': {
            'event_sl_max': ''
        },
        'event_state': {
            'event_state_0': 'on',
            'event_state_1': 'on',
            'event_state_2': 'on',
            'event_state_3': 'on'
        },
        'event_text': {
            'event_text': ''
        },
        'hostregex': {
            'host_regex': ''
        }
    },
    'datasource': 'mkeventd_events',
    'description': u'Table of all currently open events (handled and unhandled)\n',
    'group_painters': [],
    'hidden': False,
    'hidebutton': False,
    'icon': 'mkeventd',
    'layout': 'mobilelist',
    'linktitle': u'Events',
    'mobile': True,
    'name': 'ec_events_mobile',
    'num_columns': 1,
    'owner': 'cmkadmin',
    'painters': [
        ('event_id', 'ec_event_mobile', None),
        ('event_state', None, None),
        ('event_host', 'ec_events_of_host', None),
        ('event_application', None, None),
        ('event_text', None, None),
        ('event_last', None, None),
    ],
    'public': True,
    'single_infos': [],
    'sorters': [('event_last', False)],
    'title': u'Events',
    'topic': u'Event Console',
    'user_sortable': True,
}
