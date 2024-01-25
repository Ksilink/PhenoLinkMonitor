# import streamlit as st

# import asyncio
from nicegui import ui

import pandas as pd

# import numpy as np
import zmq
from datetime import datetime
from uuid import uuid4

# import plotly.graph_objects as go

# from streamlit.web.server import Server
# from streamlit.runtime.scriptrunner import get_script_run_ctx as get_report_ctx
from collections import defaultdict


def zmq_setup(server):
    try:
        context = zmq.Context()

        socket = context.socket(zmq.DEALER)
        socket.setsockopt(zmq.LINGER, 0)

        #        sessid = get_report_ctx().session_id
        socket.setsockopt_unicode(zmq.ROUTING_ID, str(uuid4()))

        r = socket.connect(f"tcp://{server}")

    except Exception as e:
        print("Error occured", e.errno, e.strerror)
        pass
    return context, socket


def zmq_call(command):
    try:
        #        context, socket = zmq_setup("localhost:13555")

        context, socket = zmq_setup("192.168.2.127:13555")
        if not type(command) == list:
            command = [command]

        messages = [
            #        b"1234567890ABCDEFG",  # UUID
            b"",  # Empty
            b"MDPC01_PL",  # Client code
        ] + [c.encode("utf-8") for c in command]

        for msg in messages[:-1]:
            socket.send(msg, flags=zmq.SNDMORE)
        socket.send(messages[-1])
        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)
        while True:
            socks = dict(poller.poll(timeout=2500))
            if socket in socks and socks[socket] == zmq.POLLIN:
                # string = socket.recv()
                res = socket.recv_multipart()[3:]
                socket.close()
                context.term()
                return res

    except Exception as e:
        print("Error occured", e.errno, e.strerror)
        pass
    finally:
        context.term()
    return []


# Plugins List
# st.write([x.decode() for x in zmq_call("mmi.list")])

rows = ui.row()
dark = ui.dark_mode()
dark.enable()
with ui.row():
    ui.label("Switch mode:")
    ui.button("Dark", on_click=dark.enable)
    ui.button("Light", on_click=dark.disable)


# Worker ID|Worker Server # plugin|plugin version # ....
def render():
    rows.clear()

    with rows:
        loads = [
            [l.split("#") for l in x.decode().split("|")]
            for x in zmq_call("mmi.health")
        ]
        #        print(loads[0][1])
        health = {}
        for i in range(len(loads)):
            loads[i][2] = {
                a.split(":")[0]: float(a.split(":")[-1]) for a in loads[i][2] if a != ""
            }
            health[loads[i][1][-1][1:]] = loads[i][2]

        # print(health)
        services = [
            [l.split("|") for l in x.decode().split("#")]
            for x in zmq_call("mmi.list_services")
        ]
        services = [x for x in services if len(x) > 1]

        # df = pd.DataFrame(services).T
        # 2023-09-18 11:40:18 +0200
        srv = [c[0][1].replace("_", "") for c in services]
        pluginsraw = {
            c[0][1].replace("_", ""): {x[0]: x[1] for x in c[1:]} for c in services
        }
        plugins = {
            c[0][1].replace("_", ""): {
                x[0]: datetime.strptime(
                    " ".join(x[1].split(" ")[1:]), "%Y-%m-%d %H:%M:%S %z"
                )
                for x in c[1:]
            }
            for c in services
        }

        df = pd.DataFrame(plugins)
        # print(df.describe())
        mx = df.max(axis=1, skipna=True)
        plugin_status = {}
        for idx, row in df.iterrows():
            plugin_status[idx] = row >= mx[idx]

        def color_boolean(val):
            color = ""
            if val == True:
                color = "green"
            elif val == False:
                color = "red"
            return "background-color: %s" % color

        # print(plugin_status)
        df = pd.DataFrame(plugin_status).T
        df["Name"] = df.index

        runtime = {
            "Pending": [],
            "Running": [],
            "Workers": defaultdict(lambda: 0),
            "Waiting": defaultdict(lambda: 0),
        }

        # Status of workers Running have some process currently waiting for finish / Pending (work in the queue) / Workers (alive workers) / Waiting (i.e. available for work)
        for x in zmq_call("mmi.workers"):
            x = x.decode().split(":")
            if x[0] in ["Waiting", "Workers"]:
                name = " ".join(x[1][1:].split("|")[-2:])
                for pk in plugins.keys():
                    if name.endswith(pk):
                        name = pk

                runtime[x[0]][name] += 1
            else:
                runtime[x[0]].append(x[1][1:])

        # print(runtime)

        cancellable = defaultdict(lambda: 0)
        for x in runtime["Pending"]:
            cancellable[x] += 1

        with ui.grid(columns=2).style("grid-template-columns: auto auto auto auto 1fr"):
            # Visual starts here

            with ui.card():
                ui.label("Status")
                with ui.grid(columns=2):
                    ui.label("Pending Jobs")
                    ui.label(len(runtime["Pending"]))
                    with ui.expansion("Jobs Processes").classes("col-span-2"):
                        with ui.grid(columns=2):
                            for x in cancellable:
                                xs = x.split("|")
                                with ui.label(xs[0]):
                                    ui.badge(str(cancellable[x]), color="green").props(
                                        "floating"
                                    )
                                ui.button(
                                    "Cancel",
                                    on_click=lambda: (
                                        zmq_call(["mmi.cancel", xs[1]]),
                                        render(),
                                    ),
                                )

                    ui.label("Running Jobs")
                    ui.label(len(runtime["Running"]))

            # Visual starts here
            with ui.card():
                with ui.grid(columns=8):
                    ui.label("Connected Servers")
                    ui.label("CPUs")
                    ui.label("Working")
                    ui.label("% Busy")
                    ui.label("Used Memory")
                    ui.label("Pl Memory")
                    ui.label("Total CPU")
                    ui.label("Pl CPU")
                    for id in df.columns:
                        if id != "Name":
                            ui.label(id)
                            ui.label(runtime["Workers"][id])
                            ui.label(runtime["Workers"][id] - runtime["Waiting"][id])
                            ui.label(
                                str(
                                    100
                                    * (
                                        1
                                        - runtime["Waiting"][id]
                                        / runtime["Workers"][id]
                                    )
                                )
                                + " %"
                            )

                            ui.circular_progress(
                                value=int(
                                    10000
                                    * health[id]["PhysicalMemoryUsed"]
                                    / health[id]["TotalPhysicalMemory"]
                                )
                                / 100,
                                min=0,
                                max=100,
                            )
                            ui.circular_progress(
                                value=int(
                                    10000
                                    * health[id]["PhenoLinkMemoryUsage"]
                                    / health[id]["TotalPhysicalMemory"]
                                )
                                / 100,
                                min=0,
                                max=100,
                            )

                            ui.circular_progress(
                                value=int(100 * health[id]["TotalWorkerCPULoad"]) / 100,
                                min=0,
                                max=100,
                            )
                            ui.circular_progress(
                                value=int(100 * health[id]["PhenoLinkWorkerCPULoad"])
                                / 100,
                                min=0,
                                max=100,
                            )

        ui.separator()
        # print(runtime)

        with ui.expansion("Available Processes", icon="work").classes("w-full"):
            # ui.table.from_pandas(
            #     df[["Name"] + [x for x in df.columns if x != "Name"]], row_key="Name"
            # )  # .T.style.applymap(color_boolean))
            # task_alt
            # elderly_woman

            with ui.grid(columns=len(df.columns)):
                ui.label("Process")
                for c in df.columns:
                    if c != "Name":
                        ui.label(c)

                for k in plugin_status.keys():
                    ui.label(k)
                    for c in df.T[k]:
                        if type(c) is bool:
                            if c:
                                ui.icon("task_alt", color="green")
                            else:
                                ui.icon("elderly_woman", color="orange")


render()
ui.timer(20, render)
ui.run()
