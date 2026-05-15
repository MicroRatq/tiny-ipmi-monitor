using System.Collections.Generic;
using LibreHardwareMonitor.Hardware;

namespace HardwareMonitorShim;

public sealed class MemorySettings : ISettings
{
    private readonly Dictionary<string, string> _values = new Dictionary<string, string>();

    public bool Contains(string name)
    {
        return _values.ContainsKey(name);
    }

    public void SetValue(string name, string value)
    {
        _values[name] = value;
    }

    public string GetValue(string name, string value)
    {
        return _values.TryGetValue(name, out string stored) ? stored : value;
    }

    public void Remove(string name)
    {
        _values.Remove(name);
    }
}
