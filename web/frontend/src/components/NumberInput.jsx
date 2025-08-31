import React, { useState, useRef, useEffect } from "react";

const NumberInput = ({
  value,
  onChange,
  min = -Infinity,
  max = Infinity,
  step = 1,
  decimals = null,
  className = "",
  ...props
}) => {
  const formatValue = (val) => {
    if (decimals !== null && typeof val === "number") {
      return val.toFixed(decimals);
    }
    return val;
  };

  const [localValue, setLocalValue] = useState(formatValue(value));
  const [isEditing, setIsEditing] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!isEditing) {
      setLocalValue(formatValue(value));
    }
  }, [value, isEditing]);

  const handleFocus = (e) => {
    setIsEditing(true);
  };

  const commitValue = () => {
    let numValue = parseFloat(localValue);

    if (isNaN(numValue)) {
      numValue = min !== -Infinity ? min : 0;
    }

    if (numValue < min) numValue = min;
    if (numValue > max) numValue = max;

    setLocalValue(formatValue(numValue));
    onChange(numValue);
    setIsEditing(false);
  };

  const handleBlur = () => {
    commitValue();
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitValue();
      inputRef.current?.blur();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setLocalValue(formatValue(value));
      setIsEditing(false);
      inputRef.current?.blur();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const newValue = Math.min(max, parseFloat(localValue) + step);
      setLocalValue(formatValue(newValue));
      onChange(newValue);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const newValue = Math.max(min, parseFloat(localValue) - step);
      setLocalValue(formatValue(newValue));
      onChange(newValue);
    }
  };

  const handleWheel = (e) => {
    if (inputRef.current === document.activeElement) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -step : step;
      const currentValue = parseFloat(localValue) || 0;
      const newValue = Math.min(max, Math.max(min, currentValue + delta));
      setLocalValue(formatValue(newValue));

      if (!isEditing) {
        onChange(newValue);
      }
    }
  };

  const handleChange = (e) => {
    setLocalValue(e.target.value);
  };

  return (
    <input
      ref={inputRef}
      type="text"
      value={localValue}
      onChange={handleChange}
      onFocus={handleFocus}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      onWheel={handleWheel}
      className={className}
      style={{ width: `${String(localValue).length + 1.5}ch`, ...props.style }}
      {...props}
    />
  );
};

export default NumberInput;
