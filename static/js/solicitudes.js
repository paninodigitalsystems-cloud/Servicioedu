async function cargarSolicitudes() {
    const res = await fetch("/api/recuperacion/pendientes");
    const d = await res.json();

    const tbody = document.getElementById("tabla-solicitudes");

    // Si no hay datos → mensaje bonito
    if (!d.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="mensaje-vacio">
                    🔔 No hay solicitudes pendientes
                </td>
            </tr>`;
        return;
    }

    // Si hay datos → tabla normal
    tbody.innerHTML = d.map(s => `
        <tr>
            <td>${s.profesor}</td>
            <td>${s.usuario}</td>
            <td>${s.fecha}</td>
            <td>${s.hora}</td>
            <td>
                <button class="btn-generar" onclick="generar('${s.usuario}')">Generar</button>
                <button class="btn-resuelto" onclick="resuelto('${s.id}')">Resuelto</button>
            </td>
        </tr>
    `).join("");
}

async function generar(usuario) {
    await fetch("/api/recuperacion/generar", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({usuario})
    });
    cargarSolicitudes();
}

async function resuelto(id) {
    await fetch("/api/recuperacion/resuelto", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id})
    });
    cargarSolicitudes();
}

cargarSolicitudes();
