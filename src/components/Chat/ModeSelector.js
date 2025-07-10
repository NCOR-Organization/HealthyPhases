import React from 'react';
import PropTypes from 'prop-types';
import styles from './Chat.module.css';

function ModeSelector({ mode, onModeChange }) {
  const handleClick = () => {
    const newMode = mode === 'test' ? 'naas' : 'test';
    onModeChange(newMode);
  };

  return (
    <button 
      onClick={handleClick}
      className={styles.reloadButton}
      aria-label="Toggle AI Mode"
    >
      {mode === 'test' ? 'Switch to Naas' : 'Switch to Test Mode'}
    </button>
  );
}

ModeSelector.propTypes = {
  mode: PropTypes.oneOf(['test', 'naas']).isRequired,
  onModeChange: PropTypes.func.isRequired,
};

export default ModeSelector; 