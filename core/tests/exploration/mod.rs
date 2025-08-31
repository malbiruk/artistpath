pub mod bfs;
pub mod dijkstra;

use memmap2::Mmap;
use rustc_hash::FxHashMap;
use uuid::Uuid;

pub struct TestGraph {
    pub taylor_id: Uuid,
    pub _olivia_id: Uuid,
    pub _billie_id: Uuid,
    pub _finneas_id: Uuid,
    pub graph_index: FxHashMap<Uuid, u64>,
    pub mmap: Mmap,
}

impl TestGraph {
    pub fn create() -> Self {
        let taylor_id = Uuid::parse_str("20244d07-534f-4eff-b4d4-930878889970").unwrap();
        let olivia_id = Uuid::parse_str("6925db17-f35e-42f3-a4eb-84ee6bf5d4b0").unwrap();
        let billie_id = Uuid::parse_str("f4abc0b5-3f7a-4eff-8f78-ac078dbce533").unwrap();
        let finneas_id = Uuid::parse_str("151cd917-1ee2-4702-859f-90899ad897f8").unwrap();

        let (mmap, graph_index) = create_test_graph_data(&[
            (taylor_id, vec![(olivia_id, 1.0)]),
            (olivia_id, vec![(billie_id, 0.8), (taylor_id, 1.0)]),
            (billie_id, vec![(finneas_id, 1.0), (olivia_id, 0.8)]),
            (finneas_id, vec![(billie_id, 1.0)]),
        ]);

        Self {
            taylor_id,
            _olivia_id: olivia_id,
            _billie_id: billie_id,
            _finneas_id: finneas_id,
            graph_index,
            mmap,
        }
    }
}

fn create_test_graph_data(
    connections: &[(Uuid, Vec<(Uuid, f32)>)],
) -> (Mmap, FxHashMap<Uuid, u64>) {
    use byteorder::{LittleEndian, WriteBytesExt};
    use memmap2::MmapOptions;
    use std::io::{Seek, Write};
    use tempfile::NamedTempFile;

    let mut file = NamedTempFile::new().unwrap();
    let mut index = FxHashMap::default();

    for (artist_id, artist_connections) in connections {
        let position = file.stream_position().unwrap();
        index.insert(*artist_id, position);

        file.write_all(&artist_id.into_bytes()).unwrap();
        file.write_u32::<LittleEndian>(artist_connections.len() as u32)
            .unwrap();

        for (connected_id, similarity) in artist_connections {
            file.write_all(&connected_id.into_bytes()).unwrap();
            file.write_f32::<LittleEndian>(*similarity).unwrap();
        }
    }

    file.flush().unwrap();
    let mmap = unsafe { MmapOptions::new().map(file.as_file()).unwrap() };

    (mmap, index)
}
