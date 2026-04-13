export interface CpuInfo {
  overall_percent: number;
  per_core_percent: number[];
  frequency_mhz: number | null;
  process_count: number;
}

export interface RamInfo {
  used_bytes: number;
  total_bytes: number;
  available_bytes: number;
  swap_used_bytes: number;
  swap_total_bytes: number;
}

export interface DiskMount {
  mountpoint: string;
  used_bytes: number;
  total_bytes: number;
  percent: number;
  read_bytes_per_sec: number | null;
  write_bytes_per_sec: number | null;
}

export interface GpuInfo {
  name: string;
  utilization_percent: number;
  vram_used_bytes: number;
  vram_total_bytes: number;
  temperature_celsius: number | null;
}

export interface ContainerStat {
  name: string;
  status: string;
  cpu_percent: number | null;
  memory_used_bytes: number | null;
  memory_limit_bytes: number | null;
}

export interface OllamaModel {
  name: string;
  size_vram_bytes: number;
  status: string;
}

export interface SystemUsage {
  timestamp: string;
  cpu: CpuInfo;
  ram: RamInfo;
  disk: DiskMount[];
  gpu: GpuInfo | null;
  docker: ContainerStat[] | null;
  ollama: OllamaModel[] | null;
}
