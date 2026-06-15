async function cargarTemporales() {
    const res = await fetch("/api/recuperacion/activas");
    const d = await res.json();

    const tbody = document.getElementById("tabla-temporales");

    // Si no hay datos → mensaje bonito
    if (!d.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="mensaje-vacio">
                    🕒 No hay contraseñas temporales activas
                </td>
            </tr>`;
        return;
    }

    // Si hay datos → tabla normal
    tbody.innerHTML = d.map(t => `
        <tr>
            <td>${t.profesor}</td>
            <td>${t.usuario}</td>
            <td><code>${t.temporal}</code></td>
            <td>${t.fecha} ${t.hora}</td>
            <td>
                <button class="btn-invalidar" onclick="invalidar('${t.id}')">Invalidar</button>
            </td>
        </tr>
    `).join("");
}

async function invalidar(id) {
    await fetch("/api/recuperacion/invalidar", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id})
    });
    cargarTemporales();
}

cargarTemporales();
