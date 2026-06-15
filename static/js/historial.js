async function cargarHistorial() {
    const res = await fetch("/api/recuperacion/historial");
    const d = await res.json();

    const tbody = document.getElementById("tabla-historial");

    // Si no hay datos → mensaje bonito
    if (!d.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="mensaje-vacio">
                    📜 No hay historial de recuperaciones
                </td>
            </tr>`;
        return;
    }

    // Si hay datos → tabla normal
    tbody.innerHTML = d.map(h => `
        <tr>
            <td>${h.profesor}</td>
            <td>${h.usuario}</td>
            <td>${h.fecha}</td>
            <td>${h.hora}</td>
            <td>${h.generado_por}</td>
            <td>${h.estado}</td>
        </tr>
    `).join("");
}

cargarHistorial();
