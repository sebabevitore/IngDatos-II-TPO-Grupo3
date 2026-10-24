// Ingeniería de Datos II — TPO Etapa 2
// Ejecutar desde mongosh. Diseño inicial: NO incluye aplicación ni transacciones entre motores.
const dbLog = db.getSiblingDB('logistica_flota');

const collections = ['contactos','usuarios','conductores','vehiculos','puntos_entrega','rutas','paquetes','viajes','asignaciones','alertas','operaciones'];
for (const name of collections) {
  if (!dbLog.getCollectionNames().includes(name)) dbLog.createCollection(name);
}

// Identificadores compartidos: viaje_id (string), paquete_codigo (string),
// vehiculo_patente (string), conductor_id (string), id_evento (UUID/string).
// El campo _id puede coincidir con el identificador de negocio para búsquedas exactas.

dbLog.usuarios.createIndex({ username: 1 }, { unique: true });
dbLog.usuarios.createIndex({ contacto_id: 1 }, { unique: true, sparse: true });
dbLog.conductores.createIndex({ contacto_id: 1 }, { unique: true });
dbLog.conductores.createIndex({ nro_licencia: 1 }, { unique: true });
dbLog.contactos.createIndex({ dni: 1 }, { unique: true, partialFilterExpression: { tipo: 'PERSONA', dni: { $type: 'string' } } });
dbLog.contactos.createIndex({ cuit: 1 }, { unique: true, partialFilterExpression: { tipo: 'EMPRESA', cuit: { $type: 'string' } } });

dbLog.paquetes.createIndex({ estado: 1, punto_entrega_id: 1 });
dbLog.paquetes.createIndex({ remitente_id: 1, fecha_registro: -1 });
dbLog.paquetes.createIndex({ destinatario_id: 1, fecha_registro: -1 });

dbLog.viajes.createIndex({ vehiculo_patente: 1, inicio_planificado: 1, fin_planificado: 1 });
dbLog.viajes.createIndex({ conductor_id: 1, inicio_planificado: 1, fin_planificado: 1 });
dbLog.viajes.createIndex({ estado: 1, ruta_id: 1 });

dbLog.asignaciones.createIndex({ viaje_id: 1, estado: 1 });
dbLog.asignaciones.createIndex({ paquete_codigo: 1, fecha_asignacion: 1 });
// Garantía: como máximo una asignación ACTIVA por paquete.
dbLog.asignaciones.createIndex(
  { paquete_codigo: 1 },
  { unique: true, partialFilterExpression: { estado: 'ACTIVA' }, name: 'unica_asignacion_activa_por_paquete' }
);

dbLog.alertas.createIndex({ clave_deduplicacion: 1 }, { unique: true });
dbLog.alertas.createIndex({ viaje_id: 1, fecha_hora: 1 });
dbLog.operaciones.createIndex({ estado: 1, fecha_inicio: 1 });

print('Colecciones e índices de MongoDB preparados en logistica_flota');
printjson(dbLog.getCollectionNames());
