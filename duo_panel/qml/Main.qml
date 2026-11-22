import QtQuick
import QtQuick.Window

Window {
    id: win
    width: 1280
    height: 960
    visible: true
    visibility: startFullscreen ? Window.FullScreen : Window.Windowed
    title: "Duo Panel"
    color: bg

    // ---- theme (all colours come from duo_panel/themes.py) -----------------
    readonly property var th: backend.theme
    readonly property color bg: th.bg
    readonly property color card: th.card
    readonly property color line: th.line
    readonly property color text: th.text
    readonly property color muted: th.muted
    readonly property color accent: th.accent
    readonly property color accent2: th.accent2
    readonly property color onAccent: th.onAccent
    readonly property color good: th.good
    readonly property color warn: th.warn
    readonly property color bad: th.bad
    readonly property int radius: th.radius
    readonly property string face: th.face
    readonly property int weight: th.weight

    // ---- data ----------------------------------------------------------------
    readonly property var d: backend.data
    readonly property var cpu: d.cpu || ({ total: 0, cores: [], clusters: [], load1: 0 })
    readonly property var gpu: d.gpu || null
    readonly property var temps: d.temps || ({})
    readonly property var mem: d.memory || ({ total: 1, used: 0, pct: 0, swap_total: 0, swap_used: 0 })
    readonly property var bat: d.battery || null
    readonly property var fan: d.fan || null
    readonly property var net: d.network || ({ rx_bps: 0, tx_bps: 0 })
    readonly property var disks: d.disks || []
    readonly property var hist: d.history || ({ cpu: [], gpu: [], temp: [], watts: [] })
    readonly property var br: d.bright || ({ available: false })
    readonly property var slow: d.slow || ({})
    readonly property var wifi: slow.wifi || ({ enabled: false })
    readonly property var bt: slow.bluetooth || ({ available: false, powered: false })
    readonly property var st: slow.syncthing || ({ active: false })
    readonly property var ssh: slow.ssh || ({ active: false })
    readonly property var prof: slow.profile || ({ name: "", options: ["Eco", "Balanced", "Performance"] })

    function gb(b) { return (b / 1073741824).toFixed(1) }
    function rate(bps) {
        if (bps >= 1048576) return (bps / 1048576).toFixed(1) + " MB/s"
        if (bps >= 1024) return Math.round(bps / 1024) + " KB/s"
        return Math.round(bps) + " B/s"
    }
    function dur(m) {
        if (!m) return ""
        var h = Math.floor(m / 60)
        return h > 0 ? h + " h " + (m % 60) + " m" : m + " m"
    }
    function tcol(c) { return c >= 85 ? bad : c >= 72 ? warn : good }
    function pcol(p) { return p >= 90 ? bad : p >= 75 ? warn : accent }
    function bcol(p, status) { return status === "Charging" ? good : p <= 15 ? bad : p <= 30 ? warn : good }
    function n0(v) { return Math.round(v) }
    function has(v) { return v !== null && v !== undefined }

    // ---- building blocks ------------------------------------------------------
    component Card: Rectangle {
        property string heading: ""
        property string note: ""
        default property alias content: body.data
        radius: win.radius
        color: win.card
        border.color: win.line
        border.width: 1
        Text {
            x: 22; y: 15
            text: parent.heading
            color: win.muted
            font.family: win.face; font.pixelSize: 21; font.weight: win.weight; font.letterSpacing: 1.2
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 22; y: 15
            text: parent.note
            color: win.muted
            font.family: win.face; font.pixelSize: 21
        }
        Item { id: body; anchors.fill: parent; anchors.topMargin: 50; anchors.leftMargin: 22; anchors.rightMargin: 22; anchors.bottomMargin: 14 }
    }

    component Spark: Canvas {
        property var values: []
        property color tint: win.accent
        property real maxValue: 0
        onValuesChanged: requestPaint()
        onTintChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var w = width, h = height
            ctx.strokeStyle = win.line
            ctx.lineWidth = 1
            ctx.beginPath(); ctx.moveTo(0, h - 0.5); ctx.lineTo(w, h - 0.5); ctx.stroke()
            var v = values
            if (!v || v.length < 2) return
            var mx = maxValue > 0 ? maxValue : Math.max(1, Math.max.apply(null, v) * 1.2)
            var n = v.length
            var step = w / (Math.max(n, 30) - 1)
            function yOf(x) { return h - Math.max(0, Math.min(1, x / mx)) * (h - 6) - 3 }
            ctx.beginPath()
            ctx.moveTo(0, h)
            for (var i = 0; i < n; i++) ctx.lineTo(i * step, yOf(v[i]))
            ctx.lineTo((n - 1) * step, h)
            ctx.closePath()
            ctx.fillStyle = Qt.rgba(tint.r, tint.g, tint.b, 0.20)
            ctx.fill()
            ctx.beginPath()
            for (var j = 0; j < n; j++) { if (j === 0) ctx.moveTo(0, yOf(v[0])); else ctx.lineTo(j * step, yOf(v[j])) }
            ctx.strokeStyle = tint
            ctx.lineWidth = 2.5
            ctx.stroke()
        }
    }

    component Bar: Item {
        property real pct: 0
        property color tint: win.accent
        height: 14
        Rectangle { anchors.fill: parent; radius: Math.min(7, win.radius); color: win.line }
        Rectangle { width: parent.width * Math.max(0, Math.min(100, parent.pct)) / 100; height: parent.height; radius: Math.min(7, win.radius); color: parent.tint }
    }

    component Big: Text {
        color: win.text
        font.family: win.face; font.pixelSize: 56; font.weight: win.weight
    }
    component Sub: Text {
        color: win.muted
        font.family: win.face; font.pixelSize: 21
        elide: Text.ElideRight
    }

    component Switch: Item {
        id: sw
        property bool on: false
        property bool busy: false
        property color tint: win.accent
        signal flipped(bool value)
        width: 92; height: 52
        Rectangle { anchors.fill: parent; radius: Math.min(26, win.radius + 10); color: sw.on ? sw.tint : win.line; opacity: sw.busy ? 0.6 : 1 }
        Rectangle {
            y: 5; width: 42; height: 42; radius: Math.min(21, win.radius + 6); color: sw.on ? win.card : win.text
            x: sw.on ? sw.width - 47 : 5
            Behavior on x { NumberAnimation { duration: 110 } }
        }
        MouseArea { anchors.fill: parent; anchors.margins: -10; onClicked: sw.flipped(!sw.on) }
    }

    component Slide: Item {
        id: sl
        property real value: 0
        property color tint: win.accent
        property real floorValue: 3
        property bool dragging: false
        property real dragValue: 0
        property bool dirty: false
        property real shown: dragging ? dragValue : value
        signal moved(real v)
        height: 56
        Rectangle { y: 21; width: parent.width; height: 14; radius: Math.min(7, win.radius); color: win.line }
        Rectangle { y: 21; width: Math.max(14, parent.width * sl.shown / 100); height: 14; radius: Math.min(7, win.radius); color: sl.tint }
        Rectangle {
            y: 6; width: 44; height: 44; radius: Math.min(22, win.radius + 8); color: win.text
            border.color: sl.tint; border.width: 3
            x: Math.max(0, Math.min(parent.width - 44, (parent.width - 44) * sl.shown / 100))
        }
        Timer {
            interval: 70; repeat: true; running: sl.dragging
            onTriggered: if (sl.dirty) { sl.dirty = false; sl.moved(sl.dragValue) }
        }
        MouseArea {
            anchors.fill: parent; anchors.topMargin: -6; anchors.bottomMargin: -6
            function setFrom(mx) {
                var v = (mx - 22) / (width - 44) * 100
                sl.dragValue = Math.max(sl.floorValue, Math.min(100, v))
                sl.dirty = true
            }
            onPressed: (m) => { sl.dragging = true; setFrom(m.x) }
            onPositionChanged: (m) => { if (pressed) setFrom(m.x) }
            onReleased: { sl.dragging = false; sl.dirty = false; sl.moved(sl.dragValue) }
        }
    }

    component SliderRow: Item {
        property string label: ""
        property real value: 0
        property bool shown: true
        property color tint: win.accent
        signal moved(real v)
        height: 56
        Text { text: parent.label; width: 84; anchors.verticalCenter: parent.verticalCenter; color: win.muted; font.family: win.face; font.pixelSize: 23 }
        Slide { x: 88; width: parent.width - 88 - 70; anchors.verticalCenter: parent.verticalCenter; value: parent.value; tint: parent.tint; onMoved: (v) => parent.moved(v) }
        Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: parent.shown ? Math.round(parent.value) + "%" : "-"; color: win.text; font.family: win.face; font.pixelSize: 25; font.weight: win.weight }
    }

    component Row2: Item {
        id: r2
        property string label: ""
        property string sub: ""
        property bool on: false
        property bool busy: false
        property color tint: win.accent
        signal flipped(bool value)
        height: 70
        Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1
            Text { text: r2.label; color: win.text; font.family: win.face; font.pixelSize: 26; font.weight: win.weight }
            Sub { text: r2.sub; width: r2.width - 116 }
        }
        Switch { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; on: r2.on; busy: r2.busy; tint: r2.tint; onFlipped: (v) => r2.flipped(v) }
    }

    // ---- page: laid out for 1280x960 and scaled to whatever the window actually is -------------
    Item {
        id: stage
        width: 1280; height: 960
        anchors.centerIn: parent
        scale: Math.min(win.width / 1280, win.height / 960)
    Item {
        anchors.fill: parent
        anchors.margins: 20

        Item {
            id: header
            width: parent.width; height: 60
            Text { id: title; text: "Duo Panel"; color: win.text; font.family: win.face; font.pixelSize: 38; font.weight: win.weight; anchors.verticalCenter: parent.verticalCenter }
            Row {
                anchors.left: title.right; anchors.leftMargin: 34; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                Repeater {
                    model: backend.themes
                    Rectangle {
                        width: 44; height: 44; radius: 22
                        color: modelData.bg
                        border.width: modelData.id === win.th.id ? 4 : 2
                        border.color: modelData.id === win.th.id ? win.text : win.line
                        Rectangle { anchors.centerIn: parent; width: 20; height: 20; radius: 10; color: modelData.accent }
                        MouseArea { anchors.fill: parent; anchors.margins: -4; onClicked: backend.setTheme(modelData.id) }
                    }
                }
                Text { text: win.th.name; color: win.muted; font.family: win.face; font.pixelSize: 22; anchors.verticalCenter: parent.verticalCenter; leftPadding: 6 }
            }
            Row {
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 22
                Text { text: win.bat ? win.n0(win.bat.pct) + "%" : ""; color: win.bat ? win.bcol(win.bat.pct, win.bat.status) : win.muted; font.family: win.face; font.pixelSize: 34; font.weight: win.weight }
                Text { text: win.d.now || ""; color: win.text; font.family: win.face; font.pixelSize: 34 }
            }
        }

        Grid {
            id: stats
            y: header.height + 14
            columns: 2
            spacing: 16
            readonly property real cw: 400
            readonly property real ch: 266

            Card {
                width: stats.cw; height: stats.ch
                heading: "CPU"; note: "load " + (win.has(win.cpu.load1) ? win.cpu.load1.toFixed(1) : "-")
                Big { text: win.n0(win.cpu.total) + "%"; color: win.pcol(win.cpu.total) }
                Spark { x: 140; y: 4; width: parent.width - 140; height: 66; values: win.hist.cpu; maxValue: 100; tint: win.pcol(win.cpu.total) }
                Row {
                    y: 82; spacing: 8; height: 48
                    Repeater {
                        model: win.cpu.cores
                        Item {
                            width: (parent.parent.width - 7 * 8) / 8; height: 48
                            Rectangle { anchors.fill: parent; radius: Math.min(5, win.radius); color: win.line }
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: Math.max(3, parent.height * modelData / 100); radius: Math.min(5, win.radius); color: win.pcol(modelData) }
                        }
                    }
                }
                Row {
                    y: 142; width: parent.width
                    Repeater {
                        model: win.cpu.clusters
                        Column {
                            width: parent.width / Math.max(1, win.cpu.clusters.length)
                            Sub { text: modelData.cpus.replace("CPU ", "Core "); font.pixelSize: 19 }
                            Text { text: modelData.mhz + " MHz"; color: win.text; font.family: win.face; font.pixelSize: 21; font.weight: win.weight }
                        }
                    }
                }
            }
            Card {
                width: stats.cw; height: stats.ch
                heading: "GPU"; note: win.gpu ? "max " + win.gpu.max_mhz + " MHz" : ""
                Big { text: win.gpu ? win.gpu.mhz + " MHz" : "n/a"; font.pixelSize: 50 }
                Sub { y: 66; width: parent.width; text: win.gpu ? win.n0(win.gpu.pct) + "% of its maximum clock" : "" }
                Spark { y: 100; width: parent.width; height: 70; values: win.hist.gpu; maxValue: 100; tint: win.accent2 }
                Bar { y: 184; width: parent.width; pct: win.gpu ? win.gpu.pct : 0; tint: win.accent2 }
            }
            Card {
                width: stats.cw; height: stats.ch
                heading: "MEMORY"; note: "swap " + win.gb(win.mem.swap_used) + " GB"
                Big { text: win.gb(win.mem.used) + " GB"; font.pixelSize: 52 }
                Sub { y: 66; width: parent.width; text: "of " + win.gb(win.mem.total) + " GB  ·  " + win.n0(win.mem.pct) + "% in use" }
                Bar { y: 108; width: parent.width; pct: win.mem.pct; tint: win.pcol(win.mem.pct) }
                Row {
                    y: 140; width: parent.width
                    Repeater {
                        model: win.disks
                        Column {
                            width: parent.width / Math.max(1, win.disks.length)
                            Sub { text: modelData.label; font.pixelSize: 19 }
                            Text { text: win.gb(modelData.free) + " GB free"; color: win.text; font.family: win.face; font.pixelSize: 22; font.weight: win.weight }
                        }
                    }
                }
            }
            Card {
                width: stats.cw; height: stats.ch
                heading: "TEMPERATURE"; note: win.fan && win.has(win.fan.rpm) ? "fan " + win.fan.rpm + " rpm" : ""
                Big { text: win.has(win.temps.cpu) ? win.n0(win.temps.cpu) + "°C" : "n/a"; color: win.temps.cpu ? win.tcol(win.temps.cpu) : win.text }
                Spark { x: 190; y: 4; width: parent.width - 190; height: 66; values: win.hist.temp; maxValue: 100; tint: win.temps.cpu ? win.tcol(win.temps.cpu) : win.accent }
                Sub { y: 80; width: parent.width; text: "CPU, hottest core" }
                Row {
                    y: 118; width: parent.width
                    Repeater {
                        model: [["GPU", win.temps.gpu], ["Memory", win.temps.memory], ["Battery", win.temps.battery]]
                        Column {
                            width: parent.width / 3
                            Sub { text: modelData[0] }
                            Text { text: win.has(modelData[1]) ? win.n0(modelData[1]) + "°C" : "-"; color: modelData[1] ? win.tcol(modelData[1]) : win.muted; font.family: win.face; font.pixelSize: 32; font.weight: win.weight }
                        }
                    }
                }
            }
            Card {
                width: stats.cw; height: stats.ch
                heading: "BATTERY"; note: win.bat ? win.bat.status : ""
                Big { text: win.bat ? win.n0(win.bat.pct) + "%" : "n/a"; color: win.bat ? win.bcol(win.bat.pct, win.bat.status) : win.text }
                Text {
                    x: 190; y: 0; width: parent.width - 190
                    text: win.bat ? Math.abs(win.bat.watts).toFixed(1) + " W " + (win.bat.status === "Charging" ? "in" : "out") : ""
                    color: win.text; font.family: win.face; font.pixelSize: 28; font.weight: win.weight
                }
                Spark { x: 190; y: 38; width: parent.width - 190; height: 34; values: win.hist.watts; tint: win.accent2 }
                Bar { y: 90; width: parent.width; pct: win.bat ? win.bat.pct : 0; tint: win.bat ? win.bcol(win.bat.pct, win.bat.status) : win.accent }
                Sub { y: 120; width: parent.width; text: win.bat && win.bat.minutes ? win.dur(win.bat.minutes) + (win.bat.status === "Charging" ? " to full" : " remaining") : "" }
                Sub { y: 150; width: parent.width; text: win.bat ? win.bat.volts.toFixed(2) + " V" + (win.bat.health ? "  ·  health " + win.bat.health + "%" : "") + (win.bat.cycles ? "  ·  " + win.bat.cycles + " cycles" : "") : "" }
            }
            Card {
                width: stats.cw; height: stats.ch
                heading: "NETWORK"; note: win.wifi.enabled ? (win.wifi.ssid || "no network") : "Wi-Fi off"
                Row {
                    spacing: 36
                    Column { Sub { text: "Down" } Big { text: win.rate(win.net.rx_bps); font.pixelSize: 36 } }
                    Column { Sub { text: "Up" } Big { text: win.rate(win.net.tx_bps); font.pixelSize: 36 } }
                }
                Sub { y: 96; width: parent.width; text: win.wifi.enabled && win.has(win.wifi.signal) ? "Signal " + win.wifi.signal + "%" : "" }
                Bar { y: 128; width: parent.width; pct: win.wifi.signal || 0; tint: win.accent; visible: win.wifi.enabled }
                Sub { y: 158; width: parent.width; text: "Up " + Math.floor((win.d.uptime || 0) / 3600) + " h " + Math.floor(((win.d.uptime || 0) % 3600) / 60) + " min" }
            }
        }

        Column {
            x: stats.width + 16
            y: header.height + 14
            width: parent.width - stats.width - 16
            spacing: 16

            Card {
                width: parent.width; height: 330
                heading: "BRIGHTNESS"
                note: !win.br.available ? "service off" : win.br.locked ? "linked" : "separate"
                Row2 {
                    width: parent.width
                    label: "Link both screens"
                    sub: win.br.available ? (win.br.locked ? "Following " + (win.br.source === "bottom" ? "bottom" : "top") : "Each screen on its own") : "Brightness service is not running"
                    on: win.br.available && win.br.locked === true
                    onFlipped: (v) => backend.setLocked(v)
                }
                SliderRow { y: 80; width: parent.width; label: "Top"; value: win.br.top || 0; shown: win.br.available; onMoved: (v) => backend.setBrightness("top", v) }
                SliderRow { y: 142; width: parent.width; label: "Bottom"; value: win.br.bottom || 0; shown: win.br.available; tint: win.accent2; onMoved: (v) => backend.setBrightness("bottom", v) }
                Item {
                    y: 206; width: parent.width; height: 56; opacity: win.br.available && win.br.locked ? 1 : 0.35
                    Text { text: "Trim"; color: win.muted; font.family: win.face; font.pixelSize: 23; anchors.verticalCenter: parent.verticalCenter }
                    Row {
                        anchors.right: parent.right; spacing: 14; anchors.verticalCenter: parent.verticalCenter
                        Rectangle {
                            width: 56; height: 56; radius: Math.min(14, win.radius); color: win.line
                            Text { anchors.centerIn: parent; text: "−"; color: win.text; font.pixelSize: 34; font.family: win.face }
                            MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: if (win.br.available && win.br.locked) backend.setTrim(Math.max(-30, (win.br.trim || 0) - 1)) }
                        }
                        Text { width: 112; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter; text: ((win.br.trim || 0) > 0 ? "+" : "") + (win.br.trim || 0) + " pts"; color: win.text; font.family: win.face; font.pixelSize: 25; font.weight: win.weight }
                        Rectangle {
                            width: 56; height: 56; radius: Math.min(14, win.radius); color: win.line
                            Text { anchors.centerIn: parent; text: "+"; color: win.text; font.pixelSize: 34; font.family: win.face }
                            MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: if (win.br.available && win.br.locked) backend.setTrim(Math.min(30, (win.br.trim || 0) + 1)) }
                        }
                    }
                }
            }

            Card {
                width: parent.width; height: 342
                heading: "QUICK SETTINGS"
                Column {
                    width: parent.width
                    Row2 {
                        width: parent.width; label: "Wi-Fi"; sub: win.wifi.enabled ? (win.wifi.ssid || "searching") : "off"
                        on: win.wifi.enabled === true; busy: win.wifi.pending === true
                        onFlipped: (v) => backend.setToggle("wifi", v)
                    }
                    Row2 {
                        width: parent.width; label: "Bluetooth"; sub: win.bt.available ? (win.bt.powered ? "on" : "off") : "not available"
                        on: win.bt.powered === true; busy: win.bt.pending === true
                        onFlipped: (v) => backend.setToggle("bluetooth", v)
                    }
                    Row2 {
                        width: parent.width; label: "Syncthing"
                        sub: win.st.active ? (win.has(win.st.connected) ? win.st.connected + (win.st.connected === 1 ? " device connected" : " devices connected") : "running") : "stopped"
                        on: win.st.active === true; busy: win.st.pending === true
                        onFlipped: (v) => backend.setToggle("syncthing", v)
                    }
                    Row2 {
                        id: sshRow
                        property bool confirming: false
                        width: parent.width; label: "SSH"
                        sub: confirming ? "Tap again: this cuts remote access" : win.ssh.active ? "remote login on" : "off"
                        on: win.ssh.active === true; busy: win.ssh.pending === true
                        tint: confirming ? win.warn : win.accent
                        onFlipped: (v) => {
                            if (!v && !confirming) { confirming = true; confirmTimer.restart(); return }
                            confirming = false
                            backend.setToggle("ssh", v)
                        }
                        Timer { id: confirmTimer; interval: 4000; onTriggered: sshRow.confirming = false }
                    }
                }
            }

            Card {
                width: parent.width; height: 126
                heading: "PERFORMANCE PROFILE"
                Row {
                    width: parent.width; height: 56; spacing: 10
                    Repeater {
                        model: win.prof.options
                        Rectangle {
                            width: (parent.width - 20) / 3; height: 56; radius: Math.min(14, win.radius)
                            color: win.prof.name === modelData ? win.accent : win.line
                            Text { anchors.centerIn: parent; text: modelData; color: win.prof.name === modelData ? win.onAccent : win.text; font.family: win.face; font.pixelSize: 17; font.weight: win.weight }
                            MouseArea { anchors.fill: parent; onClicked: backend.setProfile(modelData) }
                        }
                    }
                }
            }
        }

        Text {
            anchors.left: parent.left; anchors.bottom: parent.bottom
            width: parent.width; elide: Text.ElideRight
            text: backend.toast
            color: win.warn; font.family: win.face; font.pixelSize: 22
        }
    }
    }
}
